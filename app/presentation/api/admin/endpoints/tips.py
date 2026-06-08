from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.tip_post import TipDetailResponse, TipListResponse, TipPostCreateBody, TipPostItem, TipPostUpdateBody
from app.core.deps import get_current_user, get_db
from app.domain.models.tip_post import TipPost
from app.domain.models.user import User
from app.utils.cloudinary_cleanup import destroy_cloudinary_urls


router = APIRouter(prefix="/tips", tags=["admin-tips"])


def _utcnow_naive() -> datetime:
    return datetime.utcnow()


def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _resolve_status_with_schedule(status: str, published_at: Optional[datetime]) -> tuple[str, Optional[datetime]]:
    now = _utcnow_naive()
    if status == "archived":
        return "archived", published_at

    if published_at is None:
        if status == "published":
            return "published", now
        return status, None

    if published_at <= now:
        return "published", published_at

    return "draft", published_at


async def _publish_due_posts(db: AsyncSession) -> None:
    now = _utcnow_naive()
    await db.execute(
        update(TipPost)
        .where(
            TipPost.deleted_at.is_(None),
            TipPost.status == "draft",
            TipPost.published_at.is_not(None),
            TipPost.published_at <= now,
        )
        .values(status="published", updated_at=now)
    )
    await db.commit()


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value)
    return value.strip("-") or "tip"


async def _unique_slug(db: AsyncSession, desired_slug: str, exclude_id: Optional[int] = None) -> str:
    base_slug = _slugify(desired_slug)
    slug = base_slug
    suffix = 2

    while True:
        stmt = select(TipPost.id).where(TipPost.slug == slug, TipPost.deleted_at.is_(None)).limit(1)
        if exclude_id is not None:
            stmt = stmt.where(TipPost.id != exclude_id)
        exists = (await db.execute(stmt)).first()
        if exists is None:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


async def _to_item(entity: TipPost) -> TipPostItem:
    return TipPostItem(
        id=entity.id,
        title=entity.title,
        slug=entity.slug,
        excerpt=entity.excerpt,
        content=entity.content,
        template_key=entity.template_key,
        content_blocks=entity.content_blocks or [],
        featured_image=entity.featured_image,
        category=entity.category,
        tags=[str(x) for x in (entity.tags or []) if str(x).strip()],
        status=entity.status,
        featured=bool(entity.featured),
        seo_title=entity.seo_title,
        seo_description=entity.seo_description,
        published_at=entity.published_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _collect_tip_image_urls(featured_image: Optional[str], content_blocks: Optional[list]) -> set[str]:
    urls: set[str] = set()
    if isinstance(featured_image, str) and featured_image.strip():
        urls.add(featured_image.strip())

    blocks = content_blocks if isinstance(content_blocks, list) else []
    for block in blocks:
        if not isinstance(block, dict):
            continue

        block_type = str(block.get("type") or "").strip()
        if block_type == "image":
            url = str(block.get("url") or "").strip()
            if url:
                urls.add(url)
            continue

        if block_type == "image_text":
            url = str(block.get("image_url") or "").strip()
            if url:
                urls.add(url)
            continue

        if block_type == "gallery":
            for item in block.get("images") or []:
                url = str(item or "").strip()
                if url:
                    urls.add(url)

    return urls


@router.get("", response_model=TipListResponse)
async def get_admin_tips(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_q: Optional[str] = Query(None, alias="status"),
    featured: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await _publish_due_posts(db)

    filters = [TipPost.deleted_at.is_(None)]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append((TipPost.title.ilike(q)) | (TipPost.excerpt.ilike(q)) | (TipPost.content.ilike(q)))

    if status_q and status_q in ("draft", "published", "archived"):
        filters.append(TipPost.status == status_q)

    if featured is not None:
        filters.append(TipPost.featured.is_(featured))

    total_stmt = select(func.count()).select_from(TipPost).where(*filters)
    total = int((await db.execute(total_stmt)).scalar_one())

    offset = (page - 1) * limit
    rows = (
        await db.execute(
            select(TipPost)
            .where(*filters)
            .order_by(TipPost.published_at.desc().nullslast(), TipPost.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    data = [await _to_item(row) for row in rows]
    return TipListResponse(data=data, pagination={"page": page, "limit": limit, "total": total})


@router.post("", response_model=TipDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_tip(
    body: TipPostCreateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    slug = await _unique_slug(db, body.slug or body.title)

    published_at = _to_naive_utc(body.published_at)
    resolved_status, resolved_published_at = _resolve_status_with_schedule(body.status, published_at)

    entity = TipPost(
        title=body.title.strip(),
        slug=slug,
        excerpt=(body.excerpt or "").strip() or None,
        content=body.content,
        template_key=(body.template_key or "").strip() or None,
        content_blocks=body.content_blocks or [],
        featured_image=(body.featured_image or "").strip() or None,
        category=(body.category or "").strip() or None,
        tags=[str(x).strip() for x in (body.tags or []) if str(x).strip()],
        status=resolved_status,
        featured=bool(body.featured),
        seo_title=(body.seo_title or "").strip() or None,
        seo_description=(body.seo_description or "").strip() or None,
        published_at=resolved_published_at,
    )

    db.add(entity)
    await db.commit()
    await db.refresh(entity)

    return TipDetailResponse(data=await _to_item(entity))


@router.get("/{tip_id}", response_model=TipDetailResponse)
async def get_tip_detail(
    tip_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await _publish_due_posts(db)

    row = await db.get(TipPost, tip_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip not found")
    return TipDetailResponse(data=await _to_item(row))


@router.put("/{tip_id}", response_model=TipDetailResponse)
async def update_tip(
    tip_id: int,
    body: TipPostUpdateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    await _publish_due_posts(db)

    row = await db.get(TipPost, tip_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip not found")

    previous_urls = _collect_tip_image_urls(row.featured_image, row.content_blocks)

    payload = body.model_dump(exclude_unset=True)

    if "title" in payload and payload["title"] is not None:
        row.title = payload["title"].strip()

    if "slug" in payload:
        next_slug_source = payload.get("slug") or row.title
        row.slug = await _unique_slug(db, str(next_slug_source), exclude_id=tip_id)

    for key in ("excerpt", "content", "template_key", "featured_image", "category", "seo_title", "seo_description"):
        if key in payload:
            value = payload.get(key)
            setattr(row, key, (value.strip() if isinstance(value, str) else value) or None)

    if "content_blocks" in payload:
        row.content_blocks = payload.get("content_blocks") or []

    if "tags" in payload and payload["tags"] is not None:
        row.tags = [str(x).strip() for x in payload["tags"] if str(x).strip()]

    if "featured" in payload and payload["featured"] is not None:
        row.featured = bool(payload["featured"])

    next_status = payload.get("status", row.status) or row.status
    next_published_at = row.published_at
    if "published_at" in payload:
        next_published_at = _to_naive_utc(payload.get("published_at"))

    resolved_status, resolved_published_at = _resolve_status_with_schedule(next_status, next_published_at)
    row.status = resolved_status
    row.published_at = resolved_published_at

    row.updated_at = _utcnow_naive()

    next_urls = _collect_tip_image_urls(row.featured_image, row.content_blocks)
    removed_urls = previous_urls - next_urls

    await db.commit()
    await db.refresh(row)

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    return TipDetailResponse(data=await _to_item(row))


@router.delete("/{tip_id}")
async def delete_tip(
    tip_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(TipPost, tip_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip not found")

    removed_urls = _collect_tip_image_urls(row.featured_image, row.content_blocks)

    row.deleted_at = _utcnow_naive()
    row.status = "archived"
    row.updated_at = _utcnow_naive()

    await db.commit()

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    return {"success": True}


@router.post("/upload-image")
async def upload_tip_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File tải lên phải là ảnh")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File ảnh rỗng")

    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ảnh vượt quá 10MB")

    try:
        result = cloudinary.uploader.upload(
            raw,
            folder="tips",
            resource_type="image",
            overwrite=False,
            use_filename=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload ảnh thất bại: {str(exc)}")

    secure_url = (result or {}).get("secure_url")
    if not secure_url:
        raise HTTPException(status_code=500, detail="Upload ảnh thất bại")

    return {"url": secure_url}
