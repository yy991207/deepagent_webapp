from __future__ import annotations

import json
import os
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from backend.config.deepagents_settings import settings
from backend.database.mongo_manager import get_mongo_manager  # 从本地 backend.database 导入


logger = logging.getLogger(__name__)


def _append_to_system_message(
    system_message: SystemMessage | None,
    text: str,
) -> SystemMessage:
    new_content: list[str | dict[str, str]] = list(system_message.content_blocks) if system_message else []
    if new_content:
        text = f"\n\n{text}"
    new_content.append({"type": "text", "text": text})
    return SystemMessage(content=new_content)


@dataclass(frozen=True)
class RagDocument:
    key: str
    sha256: str
    size: int
    filename: str


class _FileLock:
    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fh: Any | None = None

    def __enter__(self) -> "_FileLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+")
        import fcntl

        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fh is None:
            return
        import fcntl

        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                self._fh.close()
            finally:
                self._fh = None


class LlamaIndexRagMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        assistant_id: str,
        workspace_root: Path,
        source_files: list[str] | None = None,
        persist_dir: Path | None = None,
        top_k: int = 5,
        max_files: int = 400,
        include_exts: tuple[str, ...] = (".md", ".txt", ".py", ".rst", ".json", ".yaml", ".yml"),
    ) -> None:
        super().__init__()
        self._assistant_id = assistant_id
        self._workspace_root = workspace_root
        self._source_files = source_files
        self._top_k = top_k
        self._max_files = max_files
        self._include_exts = include_exts

        agent_dir = settings.ensure_agent_dir(assistant_id)
        if persist_dir is None:
            if source_files:
                stable = "\n".join(sorted(source_files))
                digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
                self._persist_dir = agent_dir / "rag" / "indexes" / digest
            else:
                self._persist_dir = agent_dir / "rag" / "index"
        else:
            self._persist_dir = persist_dir
        self._manifest_path = self._persist_dir / "manifest.json"
        self._lock_path = self._persist_dir / ".lock"

    def _resolve_selected_files(self) -> list[Path] | None:
        if not self._source_files:
            return None
        results: list[Path] = []
        for raw in self._source_files:
            # Mongo mode: treat raw as mongo ObjectId string
            if isinstance(raw, str) and len(raw) == 24:
                continue
            try:
                p = Path(raw).expanduser()
                if not p.is_absolute():
                    p = (self._workspace_root / p).resolve()
                else:
                    p = p.resolve()
            except Exception:
                continue
            if self._workspace_root not in p.parents and p != self._workspace_root:
                continue
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in self._include_exts:
                continue
            results.append(p)
        return results

    def _iter_mongo_documents(self) -> list[dict[str, Any]] | None:
        if not self._source_files:
            return None
        ids = [x for x in self._source_files if isinstance(x, str) and len(x) == 24]
        if not ids:
            return None

        mongo = get_mongo_manager()
        docs: list[dict[str, Any]] = []
        for doc_id in ids[: self._max_files]:
            item = mongo.get_document_bytes(doc_id=doc_id)
            if not item:
                continue
            meta, raw = item
            filename = str(meta.get("filename") or "")
            if filename and Path(filename).suffix.lower() not in self._include_exts:
                continue
            docs.append({"id": doc_id, "meta": meta, "bytes": raw})
        return docs

    def _iter_source_files(self) -> list[Path]:
        selected = self._resolve_selected_files()
        if selected is not None:
            return selected[: self._max_files]

        ignore_dirs = {
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
        results: list[Path] = []
        for path in self._workspace_root.rglob("*"):
            if len(results) >= self._max_files:
                break
            if path.is_dir():
                continue
            if any(part in ignore_dirs for part in path.parts):
                continue
            if path.suffix.lower() not in self._include_exts:
                continue
            results.append(path)
        return results

    def query(self, query: str) -> list[dict[str, Any]]:
        self._ensure_index()
        return self._retrieve(query)

    def _load_manifest(self) -> dict[str, RagDocument]:
        if not self._manifest_path.exists():
            return {}
        try:
            raw = json.loads(self._manifest_path.read_text())
        except Exception:
            return {}
        docs = {}
        for item in raw.get("documents", []):
            try:
                docs[item["key"]] = RagDocument(
                    key=item["key"],
                    sha256=str(item.get("sha256") or ""),
                    size=int(item["size"]),
                    filename=str(item.get("filename") or ""),
                )
            except Exception:
                continue
        return docs

    def _write_manifest(self, docs: list[RagDocument]) -> None:
        payload = {
            "workspace_root": str(self._workspace_root),
            "documents": [
                {"key": d.key, "sha256": d.sha256, "size": d.size, "filename": d.filename}
                for d in sorted(docs, key=lambda x: x.key)
            ],
        }
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def _compute_fs_manifest(self, files: list[Path]) -> list[RagDocument]:
        docs: list[RagDocument] = []
        for p in files:
            try:
                stat = p.stat()
            except OSError:
                continue
            # fs uses mtime+size to approximate change; sha256 left empty
            docs.append(
                RagDocument(
                    key=str(p),
                    sha256=f"mtime:{stat.st_mtime}",
                    size=stat.st_size,
                    filename=p.name,
                )
            )
        return docs

    def _compute_mongo_manifest(self, docs: list[dict[str, Any]]) -> list[RagDocument]:
        out: list[RagDocument] = []
        for d in docs:
            meta = d.get("meta") or {}
            out.append(
                RagDocument(
                    key=str(d.get("id") or ""),
                    sha256=str(meta.get("sha256") or ""),
                    size=int(meta.get("size") or 0),
                    filename=str(meta.get("filename") or ""),
                )
            )
        return out

    def _is_manifest_changed(self, existing: dict[str, RagDocument], current: list[RagDocument]) -> bool:
        if not existing and not current:
            return False
        if len(existing) != len(current):
            return True
        for d in current:
            prev = existing.get(d.key)
            if prev is None:
                return True
            if prev.sha256 != d.sha256 or prev.size != d.size:
                return True
        return False

    def _configure_llamaindex_embeddings(self) -> None:
        provider = (os.environ.get("RAG_EMBEDDING_PROVIDER") or "dashscope").strip().lower()

        def _try_set_hf() -> bool:
            try:
                from llama_index.core import Settings as LlamaIndexSettings
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            except Exception:
                return False

            hf_model = os.environ.get("RAG_HF_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
            try:
                LlamaIndexSettings.embed_model = HuggingFaceEmbedding(model_name=hf_model)
                logger.info("RAG embedding fallback to hf. model=%s", hf_model)
                return True
            except Exception:
                logger.exception("RAG embedding hf init failed. model=%s", hf_model)
                return False

        if provider == "dashscope":
            api_key = os.environ.get("DASHSCOPE_API_KEY")
            if not api_key:
                _try_set_hf()
                return
            try:
                from llama_index.core import Settings as LlamaIndexSettings
                from llama_index.embeddings.dashscope import (
                    DashScopeEmbedding,
                    DashScopeTextEmbeddingModels,
                )
            except Exception:
                return

            model_name = os.environ.get(
                "RAG_DASHSCOPE_EMBEDDING_MODEL",
                DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V2,
            )
            try:
                LlamaIndexSettings.embed_model = DashScopeEmbedding(
                    model_name=model_name,
                    text_type="document",
                    api_key=api_key,
                )
            except Exception:
                logger.exception("RAG embedding dashscope init failed. model=%s", model_name)
                _try_set_hf()
                return
            return

        if provider == "openai":
            try:
                from llama_index.core import Settings as LlamaIndexSettings
                from llama_index.embeddings.openai import OpenAIEmbedding
            except Exception:
                return

            api_base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                _try_set_hf()
                return

            embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            try:
                if api_base:
                    LlamaIndexSettings.embed_model = OpenAIEmbedding(
                        model=embedding_model,
                        api_base=api_base,
                        api_key=api_key,
                    )
                else:
                    LlamaIndexSettings.embed_model = OpenAIEmbedding(
                        model=embedding_model,
                        api_key=api_key,
                    )
            except Exception:
                logger.exception("RAG embedding openai init failed. model=%s", embedding_model)
                _try_set_hf()
                return
            return

        if provider == "hf":
            _try_set_hf()
            return

    def _ensure_index(self) -> None:
        try:
            from llama_index.core import StorageContext, VectorStoreIndex
            from llama_index.core import load_index_from_storage
            from llama_index.core.schema import Document
        except Exception:
            return

        self._configure_llamaindex_embeddings()

        with _FileLock(self._lock_path):
            mongo_docs = self._iter_mongo_documents()
            if mongo_docs is not None:
                current_docs = self._compute_mongo_manifest(mongo_docs)
                files = []
            else:
                files = self._iter_source_files()
                current_docs = self._compute_fs_manifest(files)
            existing = self._load_manifest()

            index_exists = (self._persist_dir / "docstore.json").exists() or (
                self._persist_dir / "index_store.json"
            ).exists()

            if index_exists and not self._is_manifest_changed(existing, current_docs):
                logger.info(
                    "RAG index up-to-date. persist_dir=%s files=%s",
                    str(self._persist_dir),
                    len(files),
                )
                return

            self._persist_dir.mkdir(parents=True, exist_ok=True)

            logger.info(
                "RAG building index. persist_dir=%s files=%s",
                str(self._persist_dir),
                len(current_docs),
            )

            if index_exists:
                try:
                    storage_context = StorageContext.from_defaults(persist_dir=str(self._persist_dir))
                    _ = load_index_from_storage(storage_context)
                except Exception:
                    pass

            try:
                if mongo_docs is not None:
                    docs: list[Document] = []
                    for d in mongo_docs:
                        meta = d.get("meta") or {}
                        raw = d.get("bytes") or b""
                        text = bytes(raw).decode("utf-8", errors="replace")
                        docs.append(
                            Document(
                                text=text,
                                metadata={
                                    "source": str(meta.get("filename") or meta.get("rel_path") or d.get("id")),
                                    "mongo_id": str(d.get("id")),
                                    "filename": str(meta.get("filename") or ""),
                                },
                            )
                        )
                    index = VectorStoreIndex.from_documents(docs)
                else:
                    from llama_index.core import SimpleDirectoryReader

                    documents = SimpleDirectoryReader(input_files=[str(p) for p in files]).load_data()
                    index = VectorStoreIndex.from_documents(documents)
                index.storage_context.persist(persist_dir=str(self._persist_dir))
                self._write_manifest(current_docs)
                logger.info("RAG index built. persist_dir=%s", str(self._persist_dir))
            except Exception:
                logger.exception("RAG index build failed. persist_dir=%s", str(self._persist_dir))
                return

    def ensure_index(self) -> None:
        self._ensure_index()

    def _retrieve(self, query: str) -> list[dict[str, Any]]:
        try:
            from llama_index.core import StorageContext
            from llama_index.core import load_index_from_storage
        except Exception:
            return []

        self._configure_llamaindex_embeddings()

        try:
            storage_context = StorageContext.from_defaults(persist_dir=str(self._persist_dir))
            index = load_index_from_storage(storage_context)
            retriever = index.as_retriever(similarity_top_k=self._top_k)
            nodes = retriever.retrieve(query)
        except Exception:
            logger.exception("RAG retrieve failed. persist_dir=%s", str(self._persist_dir))
            return []

        logger.info(
            "RAG retrieve. persist_dir=%s top_k=%s query_len=%s",
            str(self._persist_dir),
            self._top_k,
            len(query or ""),
        )

        results: list[dict[str, Any]] = []
        for n in nodes:
            try:
                text = getattr(n, "text", "") or ""
                score = getattr(n, "score", None)
                node = getattr(n, "node", None)
                meta = getattr(node, "metadata", {}) if node is not None else {}
                source = meta.get("file_path") or meta.get("filename") or meta.get("source")
                results.append(
                    {
                        "text": text,
                        "score": score,
                        "source": source,
                        "mongo_id": meta.get("mongo_id"),
                    }
                )
            except Exception:
                continue
        logger.info("RAG hits=%s", len(results))
        for i, r in enumerate(results[: min(len(results), 20)], start=1):
            logger.info(
                "RAG hit #%s source=%s score=%s text_len=%s",
                i,
                r.get("source"),
                r.get("score"),
                len((r.get("text") or "")),
            )
        return results

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Any,
    ) -> ModelResponse:
        self._ensure_index()

        query = ""
        try:
            if request.messages:
                query = request.messages[-1].content if hasattr(request.messages[-1], "content") else ""
                if isinstance(query, list):
                    query = "".join([str(x) for x in query])
                query = str(query)
        except Exception:
            query = ""

        if not query.strip():
            return await handler(request)

        rag_hits = self._retrieve(query)
        if not rag_hits:
            return await handler(request)

        rag_text_parts = [
            "<rag_context>",
            "You must cite sources in your answer using square-bracket references like [1], [2].",
            "The numbers map to the context snippets below.",
        ]
        for idx, hit in enumerate(rag_hits, start=1):
            src = hit.get("source") or "unknown"
            score = hit.get("score")
            score_text = "" if score is None else f" score={score}"
            rag_text_parts.append(f"[{idx}{score_text}] source={src}\n{hit.get('text','')}")
        rag_text_parts.append("</rag_context>")
        rag_text = "\n\n".join(rag_text_parts)

        new_system = _append_to_system_message(request.system_message, rag_text)
        try:
            blocks = list(new_system.content_blocks)
            logger.info(
                "RAG injected into model request. blocks=%s rag_len=%s",
                len(blocks),
                len(rag_text),
            )
        except Exception:
            pass

        return await handler(request.override(system_message=new_system))


__all__ = ["LlamaIndexRagMiddleware"]
