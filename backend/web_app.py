from __future__ import annotations

import os
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import logging
import re

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.websockets import WebSocketState
from langchain_core.messages import HumanMessage, ToolMessage

import requests
from markdownify import markdownify

# 从 pip 安装的 deepagents-cli 包导入（需要先安装：pip install deepagents-cli）
try:
    from deepagents_cli.agent import create_cli_agent
    from deepagents_cli.config import create_model, settings
    from deepagents_cli.sessions import get_checkpointer
    from deepagents_cli.tools import fetch_url, http_request, web_search
except ImportError:
    raise ImportError(
        "请先安装 deepagents-cli: pip install deepagents-cli\n"
        "或者激活 deepagent conda 环境: conda activate deepagent"
    )

# 从本地 backend 模块导入自定义代码（分层结构）
from backend.database.mongo_manager import get_mongo_manager, get_beijing_time
from backend.middleware.podcast_middleware import build_podcast_middleware
from backend.services.chat_service import ChatService


# 精简项目的 BASE_DIR 就是项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

IGNORE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
}


@dataclass
class ToolBuffer:
    name: str | None = None
    tool_id: str | None = None
    args: Any = None
    args_parts: list[str] | None = None


app = FastAPI(title="DeepAgents CLI Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_root(root: str | None) -> Path:
    base = BASE_DIR
    if root is None:
        return base
    resolved = Path(root).expanduser().resolve()
    if base not in resolved.parents and resolved != base:
        raise HTTPException(status_code=400, detail="root must be inside workspace")
    return resolved


def _is_ignored(path: Path) -> bool:
    return path.name in IGNORE_DIRS


def _build_tree(root: Path, max_depth: int, depth: int = 0) -> dict[str, Any]:
    node = {"name": root.name, "path": str(root), "type": "dir", "children": []}
    if depth >= max_depth:
        return node
    try:
        for entry in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if _is_ignored(entry):
                continue
            if entry.is_dir():
                node["children"].append(_build_tree(entry, max_depth, depth + 1))
            else:
                node["children"].append({"name": entry.name, "path": str(entry), "type": "file"})
    except PermissionError:
        return node
    return node


@app.get("/api/fs/tree")
def fs_tree(root: str | None = None, max_depth: int = 2) -> dict[str, Any]:
    resolved = _resolve_root(root)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="root not found")
    return _build_tree(resolved, max_depth=max_depth)


@app.get("/api/fs/search")
def fs_search(root: str | None = None, q: str = "", limit: int = 50) -> dict[str, Any]:
    if not q.strip():
        return {"results": []}
    resolved = _resolve_root(root)
    results: list[dict[str, Any]] = []
    for path in resolved.rglob("*"):
        if len(results) >= limit:
            break
        if _is_ignored(path):
            continue
        if q.lower() in path.name.lower():
            results.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "type": "dir" if path.is_dir() else "file",
                }
            )
    return {"results": results}


@app.get("/api/fs/read")
def fs_read(
    path: str,
    root: str | None = None,
    offset: int = 1,
    limit: int = 400,
) -> dict[str, Any]:
    resolved_root = _resolve_root(root)
    try:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = (resolved_root / p).resolve()
        else:
            p = p.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc

    if resolved_root not in p.parents and p != resolved_root:
        raise HTTPException(status_code=400, detail="path must be inside workspace")
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="failed to read file") from exc

    start = max(offset - 1, 0)
    end = max(start + max(limit, 1), start)
    selected = lines[start:end]
    return {
        "path": str(p),
        "offset": offset,
        "limit": limit,
        "total_lines": len(lines),
        "content": "\n".join(selected),
    }


@app.get("/api/git/status")
def git_status(root: str | None = None) -> dict[str, Any]:
    resolved = _resolve_root(root)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=resolved,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="git not available") from exc
    if result.returncode != 0:
        return {"branch": None, "changes": [], "is_repo": False}
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    branch = lines[0].replace("## ", "") if lines else None
    changes = [line for line in lines[1:]]
    return {"branch": branch, "changes": changes, "is_repo": True}


@app.post("/api/sources/upload")
async def upload_sources(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    mongo = get_mongo_manager()

    saved: list[dict[str, Any]] = []
    for f in files:
        raw_name = (f.filename or "").strip() or "upload.bin"
        content = await f.read()

        rel_path = raw_name.replace("\\", "/").lstrip("/")
        rel_path = "_".join([p for p in rel_path.split("/") if p not in ("", ".", "..")])
        if not rel_path:
            rel_path = "upload.bin"

        stored = mongo.store_file(
            filename=Path(rel_path).name,
            rel_path=rel_path,
            content_bytes=content,
        )

        saved.append(
            {
                "id": stored.id,
                "sha256": stored.sha256,
                "rel_path": stored.rel_path,
                "filename": stored.filename,
                "size": stored.size,
            }
        )

    return {"count": len(saved), "files": saved}


def _is_valid_http_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        u = urlparse(url)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def _safe_filename(name: str) -> str:
    base = (name or "").strip() or "source"
    base = re.sub(r"\s+", " ", base).strip()
    base = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff _\-\.]+", "", base).strip()
    base = base.strip(".")
    if not base:
        base = "source"
    return base[:120]


def _fetch_url_to_markdown(url: str, *, timeout: int = 30) -> tuple[str, str, str]:
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DeepAgents/1.0)"},
    )
    resp.raise_for_status()
    final_url = str(resp.url)
    html = resp.text or ""
    md = markdownify(html)
    title = ""
    try:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
    except Exception:
        title = ""
    return final_url, title, md


@app.post("/api/sources/url/parse")
async def parse_url_source(payload: dict[str, Any]) -> dict[str, Any]:
    """URL 解析接口：只做解析与预览，不做入库。

    payload:
      - url: string
      - mode: "crawl" | "llm_summary"
    """
    url = str(payload.get("url") or "").strip()
    mode = str(payload.get("mode") or "crawl").strip().lower()
    if not url or not _is_valid_http_url(url):
        raise HTTPException(status_code=400, detail="invalid url")
    if mode not in ("crawl", "llm_summary"):
        raise HTTPException(status_code=400, detail="invalid mode")

    try:
        final_url, title, md = _fetch_url_to_markdown(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed to fetch url") from exc

    content = md
    if mode == "llm_summary":
        try:
            llm = create_model()
            raw = md
            if len(raw) > 50_000:
                raw = raw[:50_000] + "\n\n[内容过长已截断]"
            prompt = (
                "请把下面网页内容整理成干净、结构化的 Markdown，并在开头给出 2-3 句中文总结。\n\n"
                f"网页标题：{title or 'unknown'}\n"
                f"URL：{final_url}\n\n"
                "网页原始内容：\n"
                f"{raw}\n\n"
                "要求：\n"
                "- 去掉广告、导航、无关内容\n"
                "- 保留关键事实、数据、时间、人物\n"
                "- 输出只要 Markdown，不要额外解释"
            )
            msg = await llm.ainvoke([HumanMessage(content=prompt)])
            content = getattr(msg, "content", "") or ""
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc) or "llm summary failed") from exc

    filename_base = _safe_filename(title) if title else "url"
    filename = f"{filename_base}.md"
    rel_path = f"url/{filename}"
    return {
        "url": final_url,
        "title": title,
        "mode": mode,
        "filename": filename,
        "rel_path": rel_path,
        "content": content,
    }


@app.get("/api/sources/list")
def list_uploaded_sources(q: str | None = None, limit: int = 200, skip: int = 0) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        docs = mongo.list_documents(q=q, limit=limit, skip=skip)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc

    return {
        "results": [
            {
                "id": d.id,
                "sha256": d.sha256,
                "filename": d.filename,
                "rel_path": d.rel_path,
                "size": d.size,
                "created_at": d.created_at,
            }
            for d in docs
        ]
    }


@app.get("/api/sources/detail")
def get_uploaded_source_detail(id: str, max_bytes: int = 200_000) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        detail = mongo.get_document_detail(doc_id=id, max_bytes=max_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc

    if detail is None:
        raise HTTPException(status_code=404, detail="not found")
    return detail


@app.post("/api/podcast/bootstrap")
def podcast_bootstrap_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        result = svc.bootstrap_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "bootstrap failed") from exc
    return result


@app.get("/api/podcast/speaker-profiles")
def podcast_list_speaker_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        svc.bootstrap_profiles()
        profiles = svc.list_speaker_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": profiles}


@app.get("/api/podcast/episode-profiles")
def podcast_list_episode_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        svc.bootstrap_profiles()
        profiles = svc.list_episode_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": profiles}


@app.post("/api/podcast/generate")
def podcast_generate(payload: dict[str, Any]) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        episode_profile = str(payload.get("episode_profile") or "").strip()
        speaker_profile = str(payload.get("speaker_profile") or "").strip()
        episode_name = str(payload.get("episode_name") or "").strip()
        source_ids = payload.get("source_ids")
        if not isinstance(source_ids, list):
            source_ids = []
        source_ids = [str(x) for x in source_ids if str(x).strip()]
        briefing_suffix = payload.get("briefing_suffix")
        briefing_suffix = str(briefing_suffix).strip() if briefing_suffix is not None else None

        if not episode_profile or not speaker_profile or not episode_name:
            raise HTTPException(status_code=400, detail="missing required fields")
        if not source_ids:
            raise HTTPException(status_code=400, detail="missing source_ids")

        svc.bootstrap_profiles()
        run = svc.create_run(
            episode_profile=episode_profile,
            speaker_profile=speaker_profile,
            source_ids=source_ids,
            episode_name=episode_name,
            briefing_suffix=briefing_suffix,
        )
        svc.start_generation_async(run_id=run.id)
        return {"run_id": run.id, "status": run.status, "created_at": run.created_at}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "generate failed") from exc


@app.post("/api/podcast/runs")
def podcast_create_run(payload: dict[str, Any]) -> dict[str, Any]:
    """创建一条播客执行记录（不触发生成）。"""
    svc = build_podcast_middleware()
    try:
        episode_profile = str(payload.get("episode_profile") or "").strip()
        speaker_profile = str(payload.get("speaker_profile") or "").strip()
        episode_name = str(payload.get("episode_name") or "").strip()
        source_ids = payload.get("source_ids")
        if not isinstance(source_ids, list):
            source_ids = []
        source_ids = [str(x) for x in source_ids if str(x).strip()]
        briefing_suffix = payload.get("briefing_suffix")
        briefing_suffix = str(briefing_suffix).strip() if briefing_suffix is not None else None

        if not episode_profile or not speaker_profile or not episode_name:
            raise HTTPException(status_code=400, detail="missing required fields")
        if not source_ids:
            raise HTTPException(status_code=400, detail="missing source_ids")

        svc.bootstrap_profiles()
        run = svc.create_run(
            episode_profile=episode_profile,
            speaker_profile=speaker_profile,
            source_ids=source_ids,
            episode_name=episode_name,
            briefing_suffix=briefing_suffix,
        )
        return {"run_id": run.id, "status": run.status, "created_at": run.created_at}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "create run failed") from exc


@app.get("/api/podcast/runs")
def podcast_list_runs(limit: int = 50, skip: int = 0) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        items = svc.list_runs(limit=limit, skip=skip)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": items}


@app.get("/api/podcast/runs/{run_id}")
def podcast_run_detail(run_id: str) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        detail = svc.get_run_detail(run_id=run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="not found")
        result = svc.get_result(run_id=run_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"run": detail, "result": result}


@app.get("/api/podcast/results/{run_id}")
def podcast_result_detail(run_id: str) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        result = svc.get_result(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="not found")
    return result


@app.get("/api/podcast/runs/{run_id}/audio")
def podcast_run_audio(run_id: str) -> FileResponse:
    svc = build_podcast_middleware()
    try:
        result = svc.get_result(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if not result:
        raise HTTPException(status_code=404, detail="not found")

    audio_file_path = str(result.get("audio_file_path") or "").strip()
    if not audio_file_path:
        raise HTTPException(status_code=404, detail="audio not ready")

    p = Path(audio_file_path)
    if not p.is_absolute():
        p = BASE_DIR / p

    data_dir = Path(os.environ.get("DEEPAGENTS_DATA_DIR") or (BASE_DIR / "data")).resolve()
    podcasts_dir = (data_dir / "podcasts").resolve()

    try:
        resolved = p.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid audio path")

    if podcasts_dir not in resolved.parents and resolved != podcasts_dir:
        raise HTTPException(status_code=403, detail="forbidden")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="audio not found")

    return FileResponse(path=str(resolved), media_type="audio/mpeg", filename=resolved.name)


@app.get("/api/chat/threads")
def chat_threads(assistant_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        threads = mongo.list_chat_threads(assistant_id=assistant_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"results": threads}


@app.get("/api/chat/history")
def chat_history(thread_id: str, limit: int = 200) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        items = mongo.get_chat_history(thread_id=thread_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"thread_id": thread_id, "messages": items}


@app.get("/api/chat/memory")
def chat_memory(thread_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"thread_id": thread_id, "assistant_id": assistant_id, "memory_text": memory_text}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    if ws.client_state != WebSocketState.CONNECTED:
        return
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        return
    except RuntimeError:
        return


@app.websocket("/ws/chat")
async def chat_socket(ws: WebSocket) -> None:
    await ws.accept()

    async with get_checkpointer() as checkpointer:
        model = create_model()

        tools = [http_request, fetch_url]
        if settings.has_tavily:
            tools.append(web_search)

        try:
            while True:
                tool_buffers: dict[str | int, ToolBuffer] = {}
                started_tools: set[str] = set()

                try:
                    raw = await ws.receive_text()
                except WebSocketDisconnect:
                    return
                except RuntimeError:
                    return
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    await _send_json(ws, {"type": "error", "message": "invalid json"})
                    continue
                if payload.get("type") != "chat.request":
                    await _send_json(ws, {"type": "error", "message": "unknown message type"})
                    continue

                assistant_id = payload.get("assistant_id") or "agent"
                if not settings._is_valid_agent_name(assistant_id):
                    await _send_json(ws, {"type": "error", "message": "invalid assistant_id"})
                    continue

                import time
                request_start_time = time.time()
                
                text = payload.get("text", "")
                file_refs = payload.get("files", [])
                thread_id = payload.get("thread_id") or f"web-{uuid.uuid4().hex[:8]}"
                
                logger.warning(f"[PERF-1] 请求接收 | thread_id={thread_id} | text_len={len(text)} | files={len(file_refs)}")
                
                if not text.strip():
                    continue

                rag_references: list[dict[str, Any]] = []
                pending_text_deltas: list[str] = []
                saw_tool_call = False
                active_tool_ids: set[str] = set()

                mongo = get_mongo_manager()
                memory_text = ""
                try:
                    memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
                except Exception:
                    memory_text = ""

                step2_time = time.time() - request_start_time
                logger.warning(f"[PERF-2] 加载记忆 | 耗时={step2_time:.3f}s | memory_len={len(memory_text or '')}")

                extra_system_prompt = ""

                attachments_meta: list[dict[str, Any]] = []
                if isinstance(file_refs, list):
                    for ref in file_refs:
                        mongo_id = str(ref)
                        filename = mongo_id
                        try:
                            detail = mongo.get_document_detail(doc_id=mongo_id)
                            if isinstance(detail, dict) and detail.get("filename"):
                                filename = str(detail.get("filename"))
                        except Exception:
                            filename = mongo_id
                        attachments_meta.append({"mongo_id": mongo_id, "filename": filename})

                if attachments_meta:
                    lines = [
                        "<selected_sources>",
                        "用户已附带来源如下（请把这些来源视为唯一上下文）：",
                    ]
                    for a in attachments_meta:
                        lines.append(f"- {a.get('filename') or a.get('mongo_id')} (id={a.get('mongo_id')})")
                    lines.extend(
                        [
                            "使用规则：",
                            "- 回答需要引用附件内容时，必须调用 rag_query 基于上述来源检索。",
                            "- 不要调用 read_file 去读取工作区路径来替代附件内容。",
                            "</selected_sources>",
                        ]
                    )
                    block = "\n".join(lines)
                    extra_system_prompt = (extra_system_prompt + "\n\n" + block).strip()
                else:
                    if memory_text.strip():
                        extra_system_prompt = (
                            (extra_system_prompt + "\n\n" + "<chat_memory>\n" + memory_text.strip() + "\n</chat_memory>")
                            .strip()
                        )
                
                step3_time = time.time() - request_start_time
                logger.warning(f"[PERF-3] 处理附件元数据 | 耗时={step3_time:.3f}s | attachments={len(attachments_meta)}")
                # 使用 ChatService 保存用户消息（带日志）
                chat_service = ChatService()
                chat_service.save_user_message(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=str(text),
                    attachments=attachments_meta,
                )

                # If the user provided selected sources and asked for a summary-like task,
                # force a single rag_query run to ensure we use the Mongo attachments
                # instead of reading workspace files.
                forced_rag_hits: list[dict[str, Any]] = []
                forced_rag_refs: list[dict[str, Any]] = []
                if attachments_meta and isinstance(file_refs, list):
                    q = str(text or "").strip()
                    if q:
                        tool_call_id = f"rag-{uuid.uuid4().hex[:8]}"
                        try:
                            mongo.upsert_tool_message(
                                thread_id=thread_id,
                                assistant_id=assistant_id,
                                tool_call_id=tool_call_id,
                                tool_name="rag_query",
                                tool_args={"query": q, "files": [str(x) for x in file_refs]},
                                tool_status="running",
                                started_at=get_beijing_time(),
                            )
                            logger.info(f"Saved RAG tool start: {tool_call_id}")
                        except Exception as e:
                            logger.error(f"Failed to save RAG tool start: {e}")
                        await _send_json(
                            ws,
                            {
                                "type": "tool.start",
                                "id": tool_call_id,
                                "name": "rag_query",
                                "args": {"query": q},
                            },
                        )

                        rag_start = time.time()
                        try:
                            from deepagents_cli.rag_middleware import LlamaIndexRagMiddleware

                            rag = LlamaIndexRagMiddleware(
                                assistant_id=assistant_id,
                                workspace_root=BASE_DIR,
                                source_files=[str(x) for x in file_refs],
                            )
                            forced_rag_hits = rag.query(q)
                        except Exception:
                            forced_rag_hits = []
                        
                        rag_time = time.time() - rag_start
                        logger.warning(f"[PERF-4] RAG 检索 | 耗时={rag_time:.3f}s | hits={len(forced_rag_hits)}")

                        for i, r in enumerate(forced_rag_hits, start=1):
                            if not isinstance(r, dict):
                                continue
                            forced_rag_refs.append(
                                {
                                    "index": i,
                                    "source": r.get("source"),
                                    "score": r.get("score"),
                                    "text": r.get("text"),
                                    "mongo_id": r.get("mongo_id"),
                                }
                            )

                        if forced_rag_refs:
                            rag_references = forced_rag_refs
                            await _send_json(
                                ws,
                                {
                                    "type": "rag.references",
                                    "references": forced_rag_refs,
                                },
                            )

                            ctx_lines = [
                                "<rag_context>",
                                "你必须基于以下检索片段回答，并用 [1][2] 形式标注引用：",
                            ]
                            for ref in forced_rag_refs[:8]:
                                src = ref.get("source") or "unknown"
                                snippet = ref.get("text") or ""
                                idx = ref.get("index")
                                ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
                            ctx_lines.append("</rag_context>")
                            extra_system_prompt = (extra_system_prompt + "\n\n" + "\n\n".join(ctx_lines)).strip()

                        try:
                            mongo.upsert_tool_message(
                                thread_id=thread_id,
                                assistant_id=assistant_id,
                                tool_call_id=tool_call_id,
                                tool_name="rag_query",
                                tool_status="done" if forced_rag_refs else "error",
                                tool_output=forced_rag_refs if forced_rag_refs else {"error": "no hits"},
                                ended_at=get_beijing_time(),
                            )
                            logger.info(f"Saved RAG tool end: {tool_call_id}")
                        except Exception as e:
                            logger.error(f"Failed to save RAG tool end: {e}")
                        await _send_json(
                            ws,
                            {
                                "type": "tool.end",
                                "id": tool_call_id,
                                "name": "rag_query",
                                "status": "success" if forced_rag_refs else "error",
                                "output": forced_rag_refs if forced_rag_refs else {"error": "no hits"},
                            },
                        )

                def rag_query(query: str) -> list[dict[str, Any]]:
                    """从当前工作区/已选来源里做语义检索，返回可用于前端引用展示的结构化结果。

                    Args:
                        query: 用户问题或检索关键词

                    Returns:
                        引用列表，每条包含：index/source/score/text/mongo_id
                    """
                    try:
                        from deepagents_cli.rag_middleware import LlamaIndexRagMiddleware

                        rag = LlamaIndexRagMiddleware(
                            assistant_id=assistant_id,
                            workspace_root=BASE_DIR,
                            source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                        )
                        hits = rag.query(query)
                        out: list[dict[str, Any]] = []
                        for i, r in enumerate(hits, start=1):
                            out.append(
                                {
                                    "index": i,
                                    "source": r.get("source"),
                                    "score": r.get("score"),
                                    "text": r.get("text"),
                                    "mongo_id": r.get("mongo_id"),
                                }
                            )
                        return out
                    except Exception:
                        return []

                step5_start = time.time()
                logger.warning(f"[PERF-5] 开始创建 Agent | 累计耗时={(step5_start - request_start_time):.3f}s")
                
                agent, _backend = create_cli_agent(
                    model=model,
                    assistant_id=assistant_id,
                    tools=[*tools, rag_query],
                    workspace_root=BASE_DIR,
                    rag_source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                    extra_system_prompt=extra_system_prompt,
                    checkpointer=checkpointer,
                    auto_approve=True,
                    enable_rag=False,
                    enable_shell=False,
                )
                
                step5_time = time.time() - step5_start
                logger.warning(f"[PERF-5] Agent 创建完成 | 耗时={step5_time:.3f}s | 累计={(time.time() - request_start_time):.3f}s")

                await _send_json(ws, {"type": "session.status", "status": "thinking"})
                
                step6_start = time.time()
                logger.warning(f"[PERF-6] 开始准备 LLM 输入 | 累计耗时={(step6_start - request_start_time):.3f}s")
                
                effective_user_text = text
                if forced_rag_refs:
                    ctx_lines = [
                        "请只基于下面的附件检索片段完成总结，禁止引入其它记忆/常识内容，且必须用 [1][2] 标注引用：",
                    ]
                    for ref in forced_rag_refs[:8]:
                        src = ref.get("source") or "unknown"
                        snippet = ref.get("text") or ""
                        idx = ref.get("index")
                        ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
                    effective_user_text = (str(text or "").strip() + "\n\n" + "\n\n".join(ctx_lines)).strip()
                
                step6_time = time.time() - step6_start
                logger.warning(f"[PERF-6] LLM 输入准备完成 | 耗时={step6_time:.3f}s | input_len={len(effective_user_text)}")

                stream_input = {"messages": [HumanMessage(content=effective_user_text)]}
                
                step7_start = time.time()
                logger.warning(f"[PERF-7] 开始调用 LLM | 累计耗时={(step7_start - request_start_time):.3f}s")
                assistant_accum: list[str] = []
                first_response_logged = False
                try:
                    async for chunk in agent.astream(
                        stream_input,
                        stream_mode=["messages"],
                        subgraphs=True,
                        config={"configurable": {"thread_id": thread_id}},
                    ):
                        if not isinstance(chunk, tuple) or len(chunk) != 3:
                            continue
                        namespace, mode, data = chunk
                        # logger.debug(f"Stream chunk: ns={namespace} mode={mode} type={type(data)}")

                        if mode != "messages":
                            continue
                        
                        # If data is a list (some graph configurations), take the last one
                        if isinstance(data, list) and data:
                            message, _metadata = data[-1], {}
                        elif isinstance(data, tuple) and len(data) == 2:
                            message, _metadata = data
                        else:
                            continue

                        if isinstance(message, ToolMessage):
                            tool_id = getattr(message, "tool_call_id", None)
                            tool_name = getattr(message, "name", "")
                            logger.info(f"Processing ToolMessage: id={tool_id} name={tool_name} status={getattr(message, 'status', 'N/A')}")

                            if tool_name == "rag_query":
                                try:
                                    raw_content = message.content
                                    if isinstance(raw_content, str):
                                        parsed = json.loads(raw_content)
                                    else:
                                        parsed = raw_content
                                    if isinstance(parsed, list):
                                        rag_references = [x for x in parsed if isinstance(x, dict)]
                                        await _send_json(
                                            ws,
                                            {
                                                "type": "rag.references",
                                                "references": rag_references,
                                            },
                                        )
                                except Exception:
                                    pass

                            if tool_id:
                                try:
                                    tool_id_str = str(tool_id)
                                    if tool_id_str in active_tool_ids:
                                        active_tool_ids.discard(tool_id_str)
                                        logger.info(f"Cleared active tool id: {tool_id_str}. Remaining: {list(active_tool_ids)}")
                                    else:
                                        logger.warning(f"Received ToolMessage for unknown/already cleared id: {tool_id_str}")
                                    
                                    mongo.upsert_tool_message(
                                        thread_id=thread_id,
                                        assistant_id=assistant_id,
                                        tool_call_id=tool_id_str,
                                        tool_name=tool_name,
                                        tool_status=str(getattr(message, "status", "success")),
                                        tool_output=message.content,
                                        ended_at=get_beijing_time(),
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to save tool end: {e}")
                                await _send_json(
                                    ws,
                                    {
                                        "type": "tool.end",
                                        "id": tool_id,
                                        "name": tool_name,
                                        "status": getattr(message, "status", "success"),
                                        "output": message.content,
                                    },
                                )

                                if saw_tool_call and not active_tool_ids and pending_text_deltas:
                                    logger.info(f"Flushing {len(pending_text_deltas)} pending text deltas")
                                    for delta in pending_text_deltas:
                                        assistant_accum.append(str(delta))
                                        await _send_json(ws, {"type": "chat.delta", "text": delta})
                                    pending_text_deltas = []
                            continue
                        if not hasattr(message, "content_blocks") and not hasattr(message, "content"):
                            continue

                        # Handle content_blocks (Anthropic style)
                        if hasattr(message, "content_blocks") and message.content_blocks:
                            for block in message.content_blocks:
                                block_type = block.get("type")
                                if block_type == "text":
                                    text_delta = block.get("text", "")
                                    if text_delta:
                                        if saw_tool_call and active_tool_ids:
                                            logger.debug(f"Buffering text delta (active tools: {list(active_tool_ids)}): {text_delta[:20]}...")
                                            pending_text_deltas.append(str(text_delta))
                                        else:
                                            if not first_response_logged:
                                                ttfb = time.time() - step7_start
                                                total_ttfb = time.time() - request_start_time
                                                logger.warning(f"[PERF-8] LLM 首次响应 | LLM耗时={ttfb:.3f}s | 总累计={total_ttfb:.3f}s")
                                                first_response_logged = True
                                            assistant_accum.append(str(text_delta))
                                            await _send_json(ws, {"type": "chat.delta", "text": text_delta})
                                elif block_type in ("tool_call_chunk", "tool_call"):
                                    chunk_name = block.get("name")
                                    chunk_args = block.get("args")
                                    chunk_id = block.get("id")
                                    chunk_index = block.get("index")
                                    buffer_key = (
                                        chunk_index if chunk_index is not None else (chunk_id or "unknown")
                                    )
                                    buffer = tool_buffers.setdefault(buffer_key, ToolBuffer(args_parts=[]))
                                    if chunk_name:
                                        buffer.name = chunk_name
                                    if chunk_id:
                                        buffer.tool_id = chunk_id
                                    if isinstance(chunk_args, dict):
                                        buffer.args = chunk_args
                                        buffer.args_parts = []
                                    elif isinstance(chunk_args, str):
                                        if chunk_args:
                                            if buffer.args_parts is None:
                                                buffer.args_parts = []
                                            if not buffer.args_parts or chunk_args != buffer.args_parts[-1]:
                                                buffer.args_parts.append(chunk_args)
                                            buffer.args = "".join(buffer.args_parts)
                                    elif chunk_args is not None:
                                        buffer.args = chunk_args
                                    
                                    if buffer.tool_id and buffer.tool_id not in started_tools and buffer.name:
                                        args_value = buffer.args
                                        if isinstance(args_value, str):
                                            try:
                                                args_value = json.loads(args_value)
                                            except json.JSONDecodeError:
                                                args_value = {"value": args_value}
                                        saw_tool_call = True
                                        try:
                                            tool_id_str = str(buffer.tool_id)
                                            active_tool_ids.add(tool_id_str)
                                            mongo.upsert_tool_message(
                                                thread_id=thread_id,
                                                assistant_id=assistant_id,
                                                tool_call_id=tool_id_str,
                                                tool_name=str(buffer.name),
                                                tool_args=args_value,
                                                tool_status="running",
                                                started_at=get_beijing_time(),
                                            )
                                            logger.info(f"Saved tool start: {tool_id_str} - {buffer.name}")
                                        except Exception as e:
                                            logger.error(f"Failed to save tool start: {e}")
                                        await _send_json(
                                            ws,
                                            {
                                                "type": "tool.start",
                                                "id": buffer.tool_id,
                                                "name": buffer.name,
                                                "args": args_value,
                                            },
                                        )
                                        started_tools.add(buffer.tool_id)
                        
                        # Handle plain content (OpenAI style)
                        elif hasattr(message, "content"):
                            # Handle plain text content
                            if isinstance(message.content, str) and message.content:
                                text_delta = message.content
                                if saw_tool_call and active_tool_ids:
                                    logger.debug(f"Buffering text content (active tools: {list(active_tool_ids)}): {text_delta[:20]}...")
                                    pending_text_deltas.append(str(text_delta))
                                else:
                                    assistant_accum.append(str(text_delta))
                                    await _send_json(ws, {"type": "chat.delta", "text": text_delta})
                            
                            # Handle tool_calls list (OpenAI style)
                            if hasattr(message, "tool_calls") and message.tool_calls:
                                for tc in message.tool_calls:
                                    tc_id = tc.get("id")
                                    tc_name = tc.get("name")
                                    tc_args = tc.get("args")
                                    
                                    if tc_id and tc_id not in started_tools and tc_name:
                                        args_value = tc_args
                                        if isinstance(args_value, str):
                                            try:
                                                args_value = json.loads(args_value)
                                            except json.JSONDecodeError:
                                                args_value = {"value": args_value}
                                        
                                        saw_tool_call = True
                                        try:
                                            active_tool_ids.add(str(tc_id))
                                            mongo.upsert_tool_message(
                                                thread_id=thread_id,
                                                assistant_id=assistant_id,
                                                tool_call_id=str(tc_id),
                                                tool_name=str(tc_name),
                                                tool_args=args_value,
                                                tool_status="running",
                                                started_at=get_beijing_time(),
                                            )
                                            logger.info(f"Saved OpenAI tool start: {tc_id} - {tc_name}")
                                        except Exception as e:
                                            logger.error(f"Failed to save tool start: {e}")
                                            
                                        await _send_json(
                                            ws,
                                            {
                                                "type": "tool.start",
                                                "id": tc_id,
                                                "name": tc_name,
                                                "args": args_value,
                                            },
                                        )
                                        started_tools.add(tc_id)
                except Exception as exc:  # noqa: BLE001
                    await _send_json(ws, {"type": "error", "message": str(exc) or "unknown error"})
                finally:
                    try:
                        assistant_text = "".join(assistant_accum).strip()
                        suggested_questions: list[str] = []
                        
                        if assistant_text:
                            # Generate 3 follow-up questions based on the conversation
                            try:
                                question_prompt = f"""基于以下对话，生成 3 个简短的延续问题（每个问题不超过 20 字），帮助用户深入了解相关内容。

用户问题：{text}

AI 回答：{assistant_text[:500]}

要求：
1. 问题要具体、可操作
2. 与当前话题紧密相关
3. 每个问题一行，不要编号
4. 只输出 3 个问题，不要其他内容"""
                                
                                question_msg = await model.ainvoke([HumanMessage(content=question_prompt)])
                                questions_text = getattr(question_msg, "content", "") or ""
                                suggested_questions = [
                                    q.strip() 
                                    for q in questions_text.strip().split("\n") 
                                    if q.strip() and not q.strip().startswith("#")
                                ][:3]
                                
                                if suggested_questions:
                                    await _send_json(ws, {
                                        "type": "suggested.questions",
                                        "questions": suggested_questions,
                                    })
                                    logger.info(f"Generated {len(suggested_questions)} suggested questions")
                            except Exception as e:
                                logger.error(f"Failed to generate suggested questions: {e}")
                            
                            # 使用 ChatService 保存 AI 回复（带日志）
                            chat_service = ChatService()
                            chat_service.save_assistant_message(
                                thread_id=thread_id,
                                assistant_id=assistant_id,
                                content=assistant_text,
                                attachments=attachments_meta,
                                references=rag_references,
                                suggested_questions=suggested_questions,
                            )
                            
                            # 保存聊天记忆（带日志）
                            chat_service.save_chat_memory(
                                thread_id=thread_id,
                                assistant_id=assistant_id,
                                user_text=str(text),
                                assistant_text=assistant_text,
                            )
                    except Exception:
                        pass
                    llm_time = time.time() - step7_start
                    total_time = time.time() - request_start_time
                    logger.warning(f"[PERF-9] LLM 调用完成 | LLM耗时={llm_time:.3f}s | 总累计={total_time:.3f}s | 输出字符={len(''.join(assistant_accum))}")
                    await _send_json(ws, {"type": "session.status", "status": "done"})
        except WebSocketDisconnect:
            return
