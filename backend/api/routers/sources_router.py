from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.database.mongo_manager import get_mongo_manager
from backend.services.source_service import SourceService
from backend.services.url_source_service import UrlSourceService


router = APIRouter()


# ========== Pydantic Models ==========

class CreateFolderRequest(BaseModel):
    """创建文件夹请求"""
    name: str
    parent_id: str | None = None


class MoveItemRequest(BaseModel):
    """移动项目请求"""
    target_parent_id: str | None = None


class ReorderRequest(BaseModel):
    """重新排序请求"""
    item_id: str
    target_id: str
    position: str  # "before" | "after" | "inside"


class ImportFromSourcesRequest(BaseModel):
    """从已有数据源导入请求"""
    source_ids: list[str]
    folder_id: str | None = None


# ========== Upload Endpoints ==========

@router.post("/api/sources/upload")
async def upload_sources(
    files: list[UploadFile] = File(...),
    parent_id: str | None = Form(default=None),
) -> dict[str, Any]:
    """上传文件，可选指定父文件夹"""
    svc = SourceService()
    return await svc.upload_sources(files, parent_id=parent_id)


@router.post("/api/sources/url/parse")
async def parse_url_source(payload: dict[str, Any]) -> dict[str, Any]:
    """URL 解析接口：只做解析与预览，不做入库。

    payload:
      - url: string
      - mode: "crawl" | "llm_summary"
    """
    svc = UrlSourceService()
    try:
        return await svc.parse_url_source(payload)
    except ValueError as exc:
        msg = str(exc) or "invalid request"
        if "invalid url" in msg:
            raise HTTPException(status_code=400, detail="invalid url") from exc
        if "invalid mode" in msg:
            raise HTTPException(status_code=400, detail="invalid mode") from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc


@router.get("/api/sources/list")
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


@router.get("/api/sources/detail")
def get_uploaded_source_detail(id: str, max_bytes: int = 200_000) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        detail = mongo.get_document_detail(doc_id=id, max_bytes=max_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc

    if detail is None:
        raise HTTPException(status_code=404, detail="not found")
    return detail


@router.patch("/api/sources/{id}")
def rename_uploaded_source(id: str, payload: dict[str, Any]) -> dict[str, Any]:
    mongo = get_mongo_manager()
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")

    try:
        ok = mongo.rename_document(doc_id=id, filename=filename)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to rename") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"success": True, "id": id, "filename": filename}


@router.delete("/api/sources/{id}")
def delete_uploaded_source(id: str) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        ok = mongo.delete_document(doc_id=id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to delete") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"success": True, "id": id}


# ========== Tree Structure Endpoints ==========

@router.get("/api/sources/tree")
def get_source_tree() -> dict[str, Any]:
    """获取完整的文件树结构"""
    mongo = get_mongo_manager()
    try:
        items = mongo.get_tree()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to get tree") from exc

    return {"items": items}


# ========== Folder Endpoints ==========

@router.post("/api/sources/folder")
def create_folder(request: CreateFolderRequest) -> dict[str, Any]:
    """创建文件夹"""
    mongo = get_mongo_manager()
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="folder name is required")

    try:
        doc = mongo.create_folder(name=name, parent_id=request.parent_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to create folder") from exc

    return {
        "success": True,
        "folder": {
            "id": doc.id,
            "filename": doc.filename,
            "parent_id": request.parent_id,
            "item_type": "folder",
            "sort_order": doc.size,  # size 字段用于存储 sort_order
        },
    }


@router.delete("/api/sources/folder/{folder_id}")
def delete_folder(folder_id: str, recursive: bool = True) -> dict[str, Any]:
    """删除文件夹，可选递归删除子项目"""
    mongo = get_mongo_manager()
    try:
        if recursive:
            deleted_count = mongo.delete_folder_recursive(folder_id=folder_id)
            return {"success": True, "deleted_count": deleted_count}
        else:
            # 非递归删除：只删除空文件夹
            ok = mongo.delete_document(doc_id=folder_id)
            if not ok:
                raise HTTPException(status_code=404, detail="folder not found")
            return {"success": True, "deleted_count": 1}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to delete folder") from exc


# ========== Move & Reorder Endpoints ==========

@router.post("/api/sources/{id}/move")
def move_item(id: str, request: MoveItemRequest) -> dict[str, Any]:
    """移动文件/文件夹到目标位置"""
    mongo = get_mongo_manager()
    try:
        ok = mongo.move_item(item_id=id, target_parent_id=request.target_parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to move item") from exc

    if not ok:
        raise HTTPException(status_code=404, detail="item not found")
    return {"success": True, "id": id, "parent_id": request.target_parent_id}


@router.post("/api/sources/reorder")
def reorder_item(request: ReorderRequest) -> dict[str, Any]:
    """重新排序/移动项目（支持拖拽排序）"""
    mongo = get_mongo_manager()
    
    if request.position not in ("before", "after", "inside"):
        raise HTTPException(status_code=400, detail="position must be 'before', 'after', or 'inside'")
    
    try:
        result = mongo.reorder_item(
            item_id=request.item_id,
            target_id=request.target_id,
            position=request.position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to reorder item") from exc

    if result is None:
        raise HTTPException(status_code=404, detail="item not found")
    return {"success": True, "item": result}


# ========== Duplicate Endpoint ==========

@router.post("/api/sources/{id}/duplicate")
def duplicate_item(id: str, target_parent_id: str | None = None) -> dict[str, Any]:
    """复制文件/文件夹到目标位置"""
    mongo = get_mongo_manager()
    try:
        result = mongo.duplicate_document(doc_id=id, target_parent_id=target_parent_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to duplicate item") from exc

    if result is None:
        raise HTTPException(status_code=404, detail="item not found")
    return {"success": True, "item": result}


# ========== Import to Folder Endpoints ==========

@router.post("/api/sources/folder/{folder_id}/upload")
async def upload_to_folder(
    folder_id: str,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """上传文件到指定文件夹"""
    svc = SourceService()
    return await svc.upload_sources(files, parent_id=folder_id)


@router.post("/api/sources/import-from-sources")
def import_from_sources(request: ImportFromSourcesRequest) -> dict[str, Any]:
    """从已有数据源复制到指定文件夹"""
    mongo = get_mongo_manager()
    results = []
    errors = []

    for source_id in request.source_ids:
        try:
            result = mongo.duplicate_document(doc_id=source_id, target_parent_id=request.folder_id)
            if result:
                results.append(result)
            else:
                errors.append({"id": source_id, "error": "not found"})
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": source_id, "error": str(exc)})

    return {
        "success": len(errors) == 0,
        "imported": results,
        "errors": errors,
    }
