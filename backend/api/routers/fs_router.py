from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.services.fs_service import FsService


router = APIRouter()


# 项目根目录：deepagents-webapp/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

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


def _get_fs_service() -> FsService:
    return FsService(base_dir=BASE_DIR, ignore_dirs=IGNORE_DIRS)


@router.get("/api/fs/tree")
def fs_tree(root: str | None = None, max_depth: int = 2) -> dict[str, Any]:
    svc = _get_fs_service()
    return svc.list_tree(root=root, max_depth=max_depth)


@router.get("/api/fs/search")
def fs_search(root: str | None = None, q: str = "", limit: int = 50) -> dict[str, Any]:
    svc = _get_fs_service()
    return svc.search(root=root, q=q, limit=limit)


@router.get("/api/fs/read")
def fs_read(
    path: str,
    root: str | None = None,
    offset: int = 1,
    limit: int = 400,
) -> dict[str, Any]:
    svc = _get_fs_service()
    return svc.read_file(path=path, root=root, offset=offset, limit=limit)


@router.get("/api/git/status")
def git_status(root: str | None = None) -> dict[str, Any]:
    resolved = _get_fs_service().resolve_root(root)
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
