from __future__ import annotations

import base64
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
    """向系统消息追加文本，保持原有结构不变。
    
    Args:
        system_message: 原始系统消息，可能为 None
        text: 要追加的文本内容
        
    Returns:
        追加文本后的新 SystemMessage
    """
    # 获取原有内容块，如果为空则初始化为空列表
    new_content: list[str | dict[str, str]] = list(system_message.content_blocks) if system_message else []
    # 如果已有内容，追加时先加两个换行符
    if new_content:
        text = f"\n\n{text}"
    # 追加新的文本块
    new_content.append({"type": "text", "text": text})
    return SystemMessage(content=new_content)


@dataclass(frozen=True)
class RagDocument:
    """RAG 文档元数据，用于检测文件变更和索引重建。
    
    Attributes:
        key: 文档唯一标识（文件路径或 mongo_id）
        sha256: 文件内容的 SHA256 哈希值，用于检测内容变更
        size: 文件大小，用于辅助检测变更
        filename: 文件名，用于展示和日志
    """
    key: str
    sha256: str
    size: int
    filename: str


class _FileLock:
    """基于 fcntl 的文件锁，用于保护 RAG 索引构建过程的并发安全。
    
    说明：
    - 使用上下文管理器协议，支持 with 语句
    - 自动创建锁文件的父目录
    - 使用排他锁（LOCK_EX），确保同一时间只有一个进程能构建索引
    """
    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fh: Any | None = None

    def __enter__(self) -> "_FileLock":
        # 确保锁文件的父目录存在
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        # 以追加模式打开文件，获取文件描述符
        self._fh = open(self._lock_path, "a+")
        import fcntl

        # 对文件描述符施加排他锁，会阻塞直到获取锁
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fh is None:
            return
        import fcntl

        try:
            # 释放文件锁
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                # 关闭文件句柄
                self._fh.close()
            finally:
                self._fh = None


class LlamaIndexRagMiddleware(AgentMiddleware):
    """基于 LlamaIndex 的 RAG 中间件，为 Agent 提供语义检索能力。
    
    功能说明：
    - 支持本地文件系统和工作区文件的语义检索
    - 支持 MongoDB 存储的文档检索
    - 自动构建和更新向量索引，基于文件变更检测
    - 支持多种嵌入模型（DashScope、OpenAI、HuggingFace）
    - 将检索结果注入到系统消息中，支持引用标记
    
    使用场景：
    - 当用户上传文件并提问时，从文件内容中检索相关信息
    - 当用户询问工作区相关问题时，从工作区文件中检索答案
    - 支持代码、文档、配置文件等多种文件类型的语义检索
    """
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
        self._source_files = source_files  # 指定的源文件列表（可以是本地路径或 mongo_id）
        self._top_k = top_k  # 检索返回的最大结果数
        self._max_files = max_files  # 最大处理文件数，防止内存溢出
        self._include_exts = include_exts  # 支持的文件扩展名

        # 确定索引持久化目录：每个 assistant 有独立的 RAG 索引存储空间
        agent_dir = settings.ensure_agent_dir(assistant_id)
        if persist_dir is None:
            # 如果指定了源文件列表，基于文件列表生成稳定的目录名
            if source_files:
                stable = "\n".join(sorted(source_files))
                digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
                self._persist_dir = agent_dir / "rag" / "indexes" / digest
            else:
                # 否则使用默认的通用索引目录
                self._persist_dir = agent_dir / "rag" / "index"
        else:
            self._persist_dir = persist_dir
        
        # 索引元数据文件路径，记录文件变更信息
        self._manifest_path = self._persist_dir / "manifest.json"
        # 文件锁路径，保护索引构建过程
        self._lock_path = self._persist_dir / ".lock"

    def _parse_filesystem_write_ref(self, raw: str) -> tuple[str, str] | None:
        """解析 filesystem_writes 引用标识。

        约定格式：fsw:{session_id}:{write_id}
        """
        text = str(raw or "").strip()
        if not text.startswith("fsw:"):
            return None
        parts = text.split(":", 2)
        if len(parts) != 3:
            return None
        session_id = parts[1].strip()
        write_id = parts[2].strip()
        if not session_id or not write_id:
            return None
        return session_id, write_id

    def _resolve_selected_files(self) -> list[Path] | None:
        """解析指定的源文件列表，返回有效的本地文件路径。
        
        处理逻辑：
        - 跳过 24 位字符串（视为 MongoDB ObjectId）
        - 将相对路径转换为基于工作区的绝对路径
        - 检查文件是否存在、是否在允许的扩展名范围内
        - 只返回在工作区范围内的文件，防止路径遍历攻击
        
        Returns:
            有效的本地文件路径列表，如果没有指定文件则返回 None
        """
        if not self._source_files:
            return None
        results: list[Path] = []
        for raw in self._source_files:
            # 跳过 MongoDB ObjectId（24位十六进制字符串）
            if isinstance(raw, str) and len(raw) == 24:
                continue
            # 跳过 filesystem_writes 引用，避免被当成本地路径解析
            if isinstance(raw, str) and self._parse_filesystem_write_ref(raw):
                continue
            try:
                # 解析路径，支持用户目录展开
                p = Path(raw).expanduser()
                if not p.is_absolute():
                    # 相对路径基于工作区根目录
                    p = (self._workspace_root / p).resolve()
                else:
                    p = p.resolve()
            except Exception:
                continue
            # 安全检查：确保文件在工作区范围内
            if self._workspace_root not in p.parents and p != self._workspace_root:
                continue
            # 检查文件存在性和类型
            if not p.exists() or not p.is_file():
                continue
            # 检查文件扩展名是否在支持范围内
            if p.suffix.lower() not in self._include_exts:
                continue
            results.append(p)
        return results

    def _iter_mongo_documents(self) -> list[dict[str, Any]] | None:
        """从 MongoDB 获取指定文档列表，用于 RAG 检索。
        
        处理逻辑：
        - 从 source_files 中筛选出 24 位字符串（MongoDB ObjectId）
        - 从 MongoDB 获取文档的元数据和二进制内容
        - 根据文件扩展名过滤文档类型
        - 限制最大文档数量，防止内存溢出
        
        Returns:
            MongoDB 文档列表，每个文档包含 id/meta/bytes 字段；如果没有指定文档则返回 None
        """
        if not self._source_files:
            return None
        # 筛选出 MongoDB ObjectId（24位十六进制字符串）与 filesystem_writes 引用
        mongo_ids: list[str] = []
        fs_write_refs: list[tuple[str, str]] = []
        for raw in self._source_files:
            if not isinstance(raw, str):
                continue
            if len(raw) == 24:
                mongo_ids.append(raw)
                continue
            fs_ref = self._parse_filesystem_write_ref(raw)
            if fs_ref:
                fs_write_refs.append(fs_ref)

        if not mongo_ids and not fs_write_refs:
            return None

        mongo = get_mongo_manager()
        docs: list[dict[str, Any]] = []
        # 限制最大文档数量，防止内存溢出
        for doc_id in mongo_ids[: self._max_files]:
            # 获取文档的元数据和二进制内容
            item = mongo.get_document_bytes(doc_id=doc_id)
            if not item:
                continue
            meta, raw = item
            filename = str(meta.get("filename") or "")
            # 根据文件扩展名过滤文档类型
            if filename and Path(filename).suffix.lower() not in self._include_exts:
                continue
            docs.append({"id": doc_id, "meta": meta, "bytes": raw})

        # 关键逻辑：支持把 agent 生成的 filesystem_writes 文档作为 RAG 来源参与检索。
        # 这样前端勾选“生成文档”后，可以直接进入同一套检索链路。
        for session_id, write_id in fs_write_refs:
            if len(docs) >= self._max_files:
                break
            try:
                write = mongo.get_filesystem_write(write_id=write_id, session_id=session_id)
            except Exception:
                continue
            if not isinstance(write, dict):
                continue

            write_meta = write.get("metadata") if isinstance(write.get("metadata"), dict) else {}
            file_path = str(write.get("file_path") or "")
            filename = Path(file_path).name if file_path else f"{write_id}.txt"
            file_type = str(write_meta.get("type") or "").strip().lower()
            suffix = Path(filename).suffix.lower()
            if not suffix and file_type:
                filename = f"{filename}.{file_type}"
                suffix = f".{file_type}"
            if suffix and suffix not in self._include_exts:
                continue

            content_bytes = b""
            binary_content = write.get("binary_content")
            if isinstance(binary_content, str) and binary_content:
                try:
                    content_bytes = base64.b64decode(binary_content)
                except Exception:
                    content_bytes = b""
            if not content_bytes:
                content = write.get("content")
                if isinstance(content, bytes):
                    content_bytes = bytes(content)
                else:
                    content_bytes = str(content or "").encode("utf-8")
            if not content_bytes:
                continue

            ref_id = f"fsw:{session_id}:{write_id}"
            docs.append(
                {
                    "id": ref_id,
                    "meta": {
                        "id": ref_id,
                        "sha256": str(write_meta.get("sha256") or hashlib.sha256(content_bytes).hexdigest()),
                        "filename": filename,
                        "rel_path": file_path or filename,
                        "size": int(write_meta.get("size") or len(content_bytes)),
                    },
                    "bytes": content_bytes,
                }
            )
        return docs

    def _iter_source_files(self) -> list[Path]:
        """遍历工作区文件，返回符合条件的文件路径列表。
        
        处理逻辑：
        - 如果有指定文件列表，优先使用解析后的文件
        - 否则递归遍历工作区，排除常见的忽略目录
        - 只返回指定扩展名的文件
        - 限制最大文件数量，防止内存溢出
        
        Returns:
            符合条件的文件路径列表
        """
        # 如果有指定文件列表，优先使用
        selected = self._resolve_selected_files()
        if selected is not None:
            return selected[: self._max_files]

        # 常见的忽略目录，避免索引不必要的文件
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
        # 递归遍历工作区
        for path in self._workspace_root.rglob("*"):
            if len(results) >= self._max_files:
                break
            if path.is_dir():
                continue
            # 跳过忽略目录中的文件
            if any(part in ignore_dirs for part in path.parts):
                continue
            # 只处理指定扩展名的文件
            if path.suffix.lower() not in self._include_exts:
                continue
            results.append(path)
        return results

    def query(self, query: str) -> list[dict[str, Any]]:
        """执行 RAG 查询，返回相关的文档片段。
        
        Args:
            query: 查询文本
            
        Returns:
            相关文档片段列表，每个片段包含 text/score/source/mongo_id 字段
        """
        self._ensure_index()
        return self._retrieve(query)

    def _load_manifest(self) -> dict[str, RagDocument]:
        """加载索引元数据文件，用于检测文件变更。
        
        Returns:
            文档元数据字典，key 为文件路径，value 为 RagDocument 对象
        """
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
        """写入索引元数据文件，记录当前索引的文件信息。
        
        Args:
            docs: 文档元数据列表
        """
        payload = {
            "workspace_root": str(self._workspace_root),
            "documents": [
                {"key": d.key, "sha256": d.sha256, "size": d.size, "filename": d.filename}
                for d in sorted(docs, key=lambda x: x.key)
            ],
        }
        # 确保目录存在
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        # 写入 JSON 文件，保持中文可读性
        self._manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def _compute_fs_manifest(self, files: list[Path]) -> list[RagDocument]:
        """计算文件系统文件的元数据，用于检测变更。
        
        说明：
        - 对于文件系统文件，使用修改时间（mtime）和文件大小来近似检测变更
        - 不计算 SHA256 哈希，因为性能开销较大
        - sha256 字段使用 "mtime:<timestamp>" 格式
        
        Args:
            files: 文件路径列表
            
        Returns:
            文档元数据列表
        """
        docs: list[RagDocument] = []
        for p in files:
            try:
                stat = p.stat()
            except OSError:
                continue
            # 使用 mtime+size 来近似检测文件变更，避免计算 SHA256 的性能开销
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
        """计算 MongoDB 文档的元数据，用于检测变更。
        
        说明：
        - 对于 MongoDB 文档，使用存储的 SHA256 哈希值来检测内容变更
        - 元数据中包含文件名、大小、哈希值等信息
        
        Args:
            docs: MongoDB 文档列表，每个文档包含 id/meta/bytes 字段
            
        Returns:
            文档元数据列表
        """
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
        """检查文件元数据是否发生变更，判断是否需要重建索引。
        
        检查逻辑：
        - 比较文档数量
        - 比较每个文档的 SHA256 哈希值和文件大小
        - 如果有新增、删除或变更的文件，则需要重建索引
        
        Args:
            existing: 现有的文档元数据字典
            current: 当前计算的文档元数据列表
            
        Returns:
            True 表示需要重建索引，False 表示无需重建
        """
        if not existing and not current:
            return False
        if len(existing) != len(current):
            return True
        for d in current:
            prev = existing.get(d.key)
            if prev is None:
                return True
            # 检查 SHA256 哈希值和文件大小是否变更
            if prev.sha256 != d.sha256 or prev.size != d.size:
                return True
        return False

    def _configure_llamaindex_embeddings(self) -> None:
        """配置 LlamaIndex 的嵌入模型，支持多种提供商。
        
        支持的提供商：
        - dashscope: 阿里云 DashScope 嵌入服务（默认）
        - openai: OpenAI 嵌入服务
        - hf: HuggingFace 本地嵌入模型
        
        兜底机制：
        - 如果指定的提供商初始化失败，自动降级到 HuggingFace
        - 如果 HuggingFace 也失败，则不设置嵌入模型
        """
        provider = (os.environ.get("RAG_EMBEDDING_PROVIDER") or "dashscope").strip().lower()

        def _try_set_hf() -> bool:
            """尝试设置 HuggingFace 嵌入模型作为兜底方案。
            
            Returns:
                True 表示设置成功，False 表示失败
            """
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
        """确保 RAG 索引存在且最新，如果不存在或文件已变更则重建索引。
        
        处理流程：
        1. 配置嵌入模型
        2. 使用文件锁保护并发构建
        3. 获取当前文件列表（MongoDB 或本地文件系统）
        4. 比较文件变更，判断是否需要重建
        5. 如需重建，则构建新的向量索引
        """
        try:
            from llama_index.core import StorageContext, VectorStoreIndex
            from llama_index.core import load_index_from_storage
            from llama_index.core.schema import Document
        except Exception:
            return

        self._configure_llamaindex_embeddings()

        # 使用文件锁保护并发构建过程
        with _FileLock(self._lock_path):
            mongo_docs = self._iter_mongo_documents()
            if mongo_docs is not None:
                current_docs = self._compute_mongo_manifest(mongo_docs)
                files = []
            else:
                files = self._iter_source_files()
                current_docs = self._compute_fs_manifest(files)
            existing = self._load_manifest()

            # 检查索引文件是否存在
            index_exists = (self._persist_dir / "docstore.json").exists() or (
                self._persist_dir / "index_store.json"
            ).exists()

            # 没有任何文档时不构建索引，避免后续加载报错
            if not current_docs:
                if index_exists and self._is_manifest_changed(existing, current_docs):
                    # 文档被清空时，清理旧索引，防止返回过期内容
                    try:
                        import shutil
                        shutil.rmtree(self._persist_dir)
                    except Exception:
                        pass
                    self._write_manifest(current_docs)
                logger.info("RAG skip index build: no documents. persist_dir=%s", str(self._persist_dir))
                return

            # 检查索引是否需要重建：索引文件存在且文件未变更时跳过
            if index_exists and not self._is_manifest_changed(existing, current_docs):
                logger.info(
                    "RAG index up-to-date. persist_dir=%s files=%s",
                    str(self._persist_dir),
                    len(files),
                )
                return

            # 确保索引目录存在
            self._persist_dir.mkdir(parents=True, exist_ok=True)

            logger.info(
                "RAG building index. persist_dir=%s files=%s",
                str(self._persist_dir),
                len(current_docs),
            )

            # 尝试加载现有索引（如果存在）
            if index_exists:
                try:
                    storage_context = StorageContext.from_defaults(persist_dir=str(self._persist_dir))
                    _ = load_index_from_storage(storage_context)
                except Exception:
                    pass

            # 构建新的向量索引
            try:
                if mongo_docs is not None:
                    # 处理 MongoDB 文档：将二进制内容转换为 LlamaIndex Document
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
                    # 处理本地文件系统：使用 SimpleDirectoryReader 读取文件
                    from llama_index.core import SimpleDirectoryReader

                    documents = SimpleDirectoryReader(input_files=[str(p) for p in files]).load_data()
                    index = VectorStoreIndex.from_documents(documents)
                
                # 持久化索引并更新元数据
                index.storage_context.persist(persist_dir=str(self._persist_dir))
                self._write_manifest(current_docs)
                logger.info("RAG index built. persist_dir=%s", str(self._persist_dir))
            except Exception:
                logger.exception(
                    "RAG index build failed. persist_dir=%s",
                    str(self._persist_dir),
                )
                # 清理损坏的索引文件，避免下次加载失败
                try:
                    import shutil
                    shutil.rmtree(self._persist_dir)
                except Exception:
                    pass

    def _retrieve(self, query: str) -> list[dict[str, Any]]:
        """执行向量检索，返回相关的文档片段。

        Args:
            query: 查询文本

        Returns:
            相关文档片段列表，每个片段包含 text/score/source/mongo_id 字段
        """

        # 延迟导入 llama_index，避免在未安装依赖时阻塞整个服务
        try:
            from llama_index.core import StorageContext, load_index_from_storage  # type: ignore
        except Exception:
            logger.exception("RAG retrieve import failed. persist_dir=%s", str(self._persist_dir))
            return []

        # 索引不存在时直接返回空，避免 FileNotFoundError
        index_exists = (self._persist_dir / "docstore.json").exists() or (
            self._persist_dir / "index_store.json"
        ).exists()
        if not index_exists:
            logger.info("RAG index missing, skip retrieve. persist_dir=%s", str(self._persist_dir))
            return []

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

        # 将检索结果转换为统一格式
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
        # 记录前 20 个检索结果的详细信息，便于调试
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
        """Agent 中间件的核心方法：在模型调用前注入 RAG 检索结果。
        
        处理流程：
        1. 确保 RAG 索引存在且最新
        2. 从用户消息中提取查询文本
        3. 执行向量检索获取相关文档片段
        4. 将检索结果格式化为引用上下文
        5. 将上下文注入到系统消息中
        6. 调用下一个处理器（通常是模型调用）
        
        Args:
            request: 模型请求对象，包含消息和系统提示
            handler: 下一个处理器（通常是模型调用）
            
        Returns:
            包含 RAG 上下文的模型响应
        """
        # 确保索引存在且最新
        self._ensure_index()

        # 从用户消息中提取查询文本
        query = ""
        try:
            if request.messages:
                query = request.messages[-1].content if hasattr(request.messages[-1], "content") else ""
                if isinstance(query, list):
                    query = "".join([str(x) for x in query])
                query = str(query)
        except Exception:
            query = ""

        # 如果没有查询内容，直接调用下一个处理器
        if not query.strip():
            return await handler(request)

        # 执行 RAG 检索
        rag_hits = self._retrieve(query)
        if not rag_hits:
            return await handler(request)

        # 格式化检索结果为引用上下文
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

        # 将 RAG 上下文注入到系统消息中
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

        # 调用下一个处理器，传入修改后的系统消息
        return await handler(request.override(system_message=new_system))


__all__ = ["LlamaIndexRagMiddleware"]
