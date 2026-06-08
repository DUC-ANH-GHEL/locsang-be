from __future__ import annotations

from datetime import datetime
from typing import Optional

import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.customer_story import (
    CustomerStoryCreateBody,
    CustomerStoryDetailResponse,
    CustomerStoryItem,
    CustomerStoryListResponse,
    CustomerStoryUpdateBody,
)
from app.core.deps import get_current_user, get_db
from app.domain.models.customer_story import CustomerStory
from app.domain.models.user import User
from app.utils.cloudinary_cleanup import destroy_cloudinary_urls


router = APIRouter(prefix="/customer-stories", tags=["admin-customer-stories"])


def _utcnow_naive() -> datetime:
    return datetime.utcnow()


async def _to_item(entity: CustomerStory) -> CustomerStoryItem:
    return CustomerStoryItem(
        id=entity.id,
        customer_name=entity.customer_name,
        pet_name=entity.pet_name,
        customer_title=entity.customer_title,
        quote=entity.quote,
        rating=max(1, min(5, int(entity.rating or 5))),
        image_url=entity.image_url,
        is_featured=bool(entity.is_featured),
        is_active=bool(entity.is_active),
        sort_order=int(entity.sort_order or 0),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.get("", response_model=CustomerStoryListResponse)
async def get_customer_stories(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filters = [CustomerStory.deleted_at.is_(None)]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append(
            (CustomerStory.customer_name.ilike(q))
            | (CustomerStory.pet_name.ilike(q))
            | (CustomerStory.customer_title.ilike(q))
            | (CustomerStory.quote.ilike(q))
        )

    if is_active is not None:
        filters.append(CustomerStory.is_active.is_(is_active))

    rows = (
        await db.execute(
            select(CustomerStory)
            .where(*filters)
            .order_by(CustomerStory.is_featured.desc(), CustomerStory.sort_order.asc(), CustomerStory.created_at.desc())
        )
    ).scalars().all()

    return CustomerStoryListResponse(data=[await _to_item(row) for row in rows])


@router.post("", response_model=CustomerStoryDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_customer_story(
    body: CustomerStoryCreateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    entity = CustomerStory(
        customer_name=body.customer_name.strip(),
        pet_name=(body.pet_name or "").strip() or None,
        customer_title=(body.customer_title or "").strip() or None,
        quote=body.quote.strip(),
        rating=max(1, min(5, int(body.rating or 5))),
        image_url=(body.image_url or "").strip() or None,
        is_featured=bool(body.is_featured),
        is_active=bool(body.is_active),
        sort_order=int(body.sort_order or 0),
    )

    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return CustomerStoryDetailResponse(data=await _to_item(entity))


@router.get("/{story_id}", response_model=CustomerStoryDetailResponse)
async def get_customer_story_detail(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(CustomerStory, story_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Customer story not found")
    return CustomerStoryDetailResponse(data=await _to_item(row))


@router.put("/{story_id}", response_model=CustomerStoryDetailResponse)
async def update_customer_story(
    story_id: int,
    body: CustomerStoryUpdateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(CustomerStory, story_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Customer story not found")

    previous_image_url = row.image_url

    payload = body.model_dump(exclude_unset=True)

    for key in ("customer_name", "pet_name", "customer_title", "quote", "image_url"):
        if key in payload:
            value = payload.get(key)
            setattr(row, key, (value.strip() if isinstance(value, str) else value) or None)

    if "rating" in payload and payload["rating"] is not None:
        row.rating = max(1, min(5, int(payload["rating"])))

    if "is_featured" in payload and payload["is_featured"] is not None:
        row.is_featured = bool(payload["is_featured"])

    if "is_active" in payload and payload["is_active"] is not None:
        row.is_active = bool(payload["is_active"])

    if "sort_order" in payload and payload["sort_order"] is not None:
        row.sort_order = int(payload["sort_order"])

    row.updated_at = _utcnow_naive()

    removed_urls = set()
    if isinstance(previous_image_url, str) and previous_image_url.strip():
        next_url = (row.image_url or "").strip() if isinstance(row.image_url, str) else ""
        if previous_image_url.strip() != next_url:
            removed_urls.add(previous_image_url.strip())

    await db.commit()
    await db.refresh(row)

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    return CustomerStoryDetailResponse(data=await _to_item(row))


@router.delete("/{story_id}")
async def delete_customer_story(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(CustomerStory, story_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Customer story not found")

    removed_urls = set()
    if isinstance(row.image_url, str) and row.image_url.strip():
        removed_urls.add(row.image_url.strip())

    row.deleted_at = _utcnow_naive()
    row.updated_at = _utcnow_naive()

    await db.commit()

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    return {"success": True}


@router.post("/upload-image")
async def upload_customer_story_image(
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
            folder="customer-stories",
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
