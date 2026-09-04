"""Uploads: backgrounds and custom icons."""

from __future__ import annotations

import re

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, DbSession, MemberUser, error
from ..models import Asset

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])

MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg", "image/gif": "gif", "image/avif": "avif"}


def _public(asset: Asset) -> dict:
    return {"id": asset.id, "kind": asset.kind, "filename": asset.filename, "content_type": asset.content_type, "size": asset.size,
            "url": f"/api/v1/assets/{asset.id}/{asset.filename}", "created_at": asset.created_at}


@router.get("", summary="List uploaded files")
def list_assets(user: CurrentUser, db: DbSession, kind: str = "") -> list[dict]:
    query = select(Asset).order_by(Asset.created_at.desc())
    if kind:
        query = query.where(Asset.kind == kind)
    return [_public(a) for a in db.scalars(query)]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Upload a background or icon")
async def upload(file: UploadFile, user: MemberUser, db: DbSession, kind: str = "background") -> dict:
    if kind not in ("background", "icon"):
        raise error("bad_kind", "kind must be background or icon.")
    content_type = file.content_type or ""
    if content_type not in ALLOWED:
        raise error("bad_type", "Only PNG, JPEG, WebP, SVG, GIF and AVIF images are accepted.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise error("too_large", "The file is larger than 12 MB.")
    if content_type == "image/svg+xml" and re.search(rb"<script|onload=|onerror=", data, re.IGNORECASE):
        raise error("bad_svg", "The SVG contains scripting and was refused.")
    asset = Asset(kind=kind, filename="pending", content_type=content_type, size=len(data), uploaded_by=user.id)
    db.add(asset)
    db.flush()
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", (file.filename or "upload").rsplit("/", 1)[-1])[:80]
    stem = safe.rsplit(".", 1)[0] or "upload"
    asset.filename = f"{stem}.{ALLOWED[content_type]}"
    directory = get_settings().uploads_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{asset.id}.{ALLOWED[content_type]}").write_bytes(data)
    db.commit()
    return _public(asset)


@router.get("/{asset_id}/{filename}", summary="Serve an uploaded file")
def serve(asset_id: int, filename: str, db: DbSession) -> FileResponse:
    """Public: boards on kiosk displays need their backgrounds without a session."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise error("not_found", "There is no such file.", status.HTTP_404_NOT_FOUND)
    path = get_settings().uploads_dir / f"{asset.id}.{ALLOWED.get(asset.content_type, 'bin')}"
    if not path.exists():
        raise error("not_found", "The file is missing on disk.", status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type=asset.content_type, headers={"Cache-Control": "public, max-age=86400"})


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an uploaded file")
def delete_asset(asset_id: int, user: MemberUser, db: DbSession) -> None:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise error("not_found", "There is no such file.", status.HTTP_404_NOT_FOUND)
    if asset.uploaded_by != user.id and user.role != "admin":
        raise error("forbidden", "Only the uploader or an administrator may delete this file.", status.HTTP_403_FORBIDDEN)
    path = get_settings().uploads_dir / f"{asset.id}.{ALLOWED.get(asset.content_type, 'bin')}"
    if path.exists():
        path.unlink()
    db.delete(asset)
    db.commit()
