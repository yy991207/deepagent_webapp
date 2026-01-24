from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # 加载 .env 环境变量，必须在其他模块导入前执行

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers.fs_router import router as fs_router
from backend.api.routers.sources_router import router as sources_router
from backend.api.routers.podcast_router import router as podcast_router
from backend.api.routers.chat_router import router as chat_router
from backend.api.routers.filesystem_router import router as filesystem_router


app = FastAPI(title="DeepAgents CLI Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fs_router)
app.include_router(sources_router)
app.include_router(podcast_router)
app.include_router(chat_router)
app.include_router(filesystem_router)


@app.on_event("shutdown")
async def _shutdown_cleanup() -> None:
    """服务退出时清理 OpenSandbox。

    说明：
    - 开发模式下如果启用 uvicorn --reload，会触发进程重启。
    - 如果不清理旧进程创建的沙箱容器，Docker 里会残留多个 sandbox，导致同一 session 出现 A 写入、B 读取。
    - 这里尽量在进程退出时清理当前进程持有的 sandbox。
    """

    try:
        from backend.services.opensandbox_backend import get_sandbox_manager

        await get_sandbox_manager().cleanup_all()
    except Exception:
        # 退出阶段不阻塞主流程
        return

__all__ = ["app"]
