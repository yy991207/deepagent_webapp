"""兼容层 RAG 中间件，转发到 webapp 内置实现。"""

from backend.middleware.rag_middleware import LlamaIndexRagMiddleware

__all__ = ["LlamaIndexRagMiddleware"]
