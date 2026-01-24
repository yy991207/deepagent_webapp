from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.database.mongo_manager import get_mongo_manager
from backend.services.source_service import SourceService
from backend.services.url_source_service import UrlSourceService


router = APIRouter()


@router.post("/api/sources/upload")
async def upload_sources(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    svc = SourceService()
    return await svc.upload_sources(files)


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
