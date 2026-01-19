from __future__ import annotations

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

__all__ = ["app"]
