"""文件系统服务模块
 
 这个文件主要做三件事：
 1) workspace root 的安全解析：保证前端传入的路径只能落在项目工作区内，避免越权读取。
 2) 文件/目录的基础能力封装：目录树构建、按文件名搜索、按行读取文件内容。
 3) 统一输出结构：返回给 API 层的都是可直接 JSON 化的 dict，API 层只负责路由与异常透传。
 
 使用方式：
 - `backend/web_app.py` 中通过 `FsService(base_dir=BASE_DIR, ignore_dirs=IGNORE_DIRS)` 创建实例
 - 路由层调用 `list_tree/search/read_file/resolve_root` 等方法
 
 说明：
 - 这里不负责权限体系与鉴权，只做“工作区边界”限制。
 - 忽略目录名单由上层传入，便于不同环境按需调整。
 """
 
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException


class FsService:
    def __init__(self, *, base_dir: Path, ignore_dirs: set[str]) -> None:
        self._base_dir = base_dir
        self._ignore_dirs = ignore_dirs

    def resolve_root(self, root: str | None) -> Path:
        base = self._base_dir
        if root is None:
            return base
        resolved = Path(root).expanduser().resolve()
        if base not in resolved.parents and resolved != base:
            raise HTTPException(status_code=400, detail="root must be inside workspace")
        return resolved

    def is_ignored(self, path: Path) -> bool:
        return path.name in self._ignore_dirs

    def build_tree(self, root: Path, *, max_depth: int, depth: int = 0) -> dict[str, Any]:
        node = {"name": root.name, "path": str(root), "type": "dir", "children": []}
        if depth >= max_depth:
            return node
        try:
            for entry in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if self.is_ignored(entry):
                    continue
                if entry.is_dir():
                    node["children"].append(self.build_tree(entry, max_depth=max_depth, depth=depth + 1))
                else:
                    node["children"].append({"name": entry.name, "path": str(entry), "type": "file"})
        except PermissionError:
            return node
        return node

    def list_tree(self, *, root: str | None, max_depth: int = 2) -> dict[str, Any]:
        resolved = self.resolve_root(root)
        if not resolved.exists():
            raise HTTPException(status_code=404, detail="root not found")
        return self.build_tree(resolved, max_depth=max_depth)

    def search(self, *, root: str | None, q: str = "", limit: int = 50) -> dict[str, Any]:
        if not q.strip():
            return {"results": []}
        resolved = self.resolve_root(root)
        results: list[dict[str, Any]] = []
        for path in resolved.rglob("*"):
            if len(results) >= limit:
                break
            if self.is_ignored(path):
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

    def read_file(self, *, path: str, root: str | None, offset: int = 1, limit: int = 400) -> dict[str, Any]:
        resolved_root = self.resolve_root(root)
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
