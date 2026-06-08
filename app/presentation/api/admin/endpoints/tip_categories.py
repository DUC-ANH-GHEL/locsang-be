from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.tip_category import (
    TipCategoryCreateBody,
    TipCategoryDetailResponse,
    TipCategoryItem,
    TipCategoryListResponse,
    TipCategoryUpdateBody,
)
from app.core.deps import get_current_user, get_db
from app.domain.models.tip_category import TipCategory
from app.domain.models.user import User


router = APIRouter(prefix="/tips/categories", tags=["admin-tip-categories"])


def _utcnow_naive() -> datetime:
    return datetime.utcnow()


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value)
    return value.strip("-") or "tip-category"


async def _unique_slug(db: AsyncSession, desired_slug: str, exclude_id: Optional[int] = None) -> str:
    base_slug = _slugify(desired_slug)
    slug = base_slug
    suffix = 2

    while True:
        stmt = select(TipCategory.id).where(TipCategory.slug == slug, TipCategory.deleted_at.is_(None)).limit(1)
        if exclude_id is not None:
            stmt = stmt.where(TipCategory.id != exclude_id)
        exists = (await db.execute(stmt)).first()
        if exists is None:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


async def _name_exists(db: AsyncSession, name: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(TipCategory.id).where(TipCategory.name.ilike(name.strip()), TipCategory.deleted_at.is_(None)).limit(1)
    if exclude_id is not None:
        stmt = stmt.where(TipCategory.id != exclude_id)
    return (await db.execute(stmt)).first() is not None


async def _to_item(entity: TipCategory) -> TipCategoryItem:
    return TipCategoryItem(
        id=entity.id,
        name=entity.name,
        slug=entity.slug,
        description=entity.description,
        is_active=bool(entity.is_active),
        sort_order=int(entity.sort_order or 0),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.get("", response_model=TipCategoryListResponse)
async def get_tip_categories(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filters = [TipCategory.deleted_at.is_(None)]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append((TipCategory.name.ilike(q)) | (TipCategory.description.ilike(q)))

    if is_active is not None:
        filters.append(TipCategory.is_active.is_(is_active))

    rows = (
        await db.execute(
            select(TipCategory)
            .where(*filters)
            .order_by(TipCategory.sort_order.asc(), TipCategory.name.asc(), TipCategory.id.asc())
        )
    ).scalars().all()

    return TipCategoryListResponse(data=[await _to_item(row) for row in rows])


@router.post("", response_model=TipCategoryDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_tip_category(
    body: TipCategoryCreateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    name = body.name.strip()
    if await _name_exists(db, name):
        raise HTTPException(status_code=400, detail="Tên danh mục đã tồn tại")

    entity = TipCategory(
        name=name,
        slug=await _unique_slug(db, body.slug or name),
        description=(body.description or "").strip() or None,
        is_active=bool(body.is_active),
        sort_order=int(body.sort_order or 0),
    )

    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return TipCategoryDetailResponse(data=await _to_item(entity))


@router.get("/{category_id}", response_model=TipCategoryDetailResponse)
async def get_tip_category_detail(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(TipCategory, category_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip category not found")
    return TipCategoryDetailResponse(data=await _to_item(row))


@router.put("/{category_id}", response_model=TipCategoryDetailResponse)
async def update_tip_category(
    category_id: int,
    body: TipCategoryUpdateBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(TipCategory, category_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip category not found")

    payload = body.model_dump(exclude_unset=True)

    if "name" in payload and payload["name"] is not None:
        next_name = payload["name"].strip()
        if await _name_exists(db, next_name, exclude_id=category_id):
            raise HTTPException(status_code=400, detail="Tên danh mục đã tồn tại")
        row.name = next_name

    if "slug" in payload:
        slug_source = payload.get("slug") or row.name
        row.slug = await _unique_slug(db, str(slug_source), exclude_id=category_id)

    if "description" in payload:
        row.description = (payload.get("description") or "").strip() or None

    if "is_active" in payload and payload["is_active"] is not None:
        row.is_active = bool(payload["is_active"])

    if "sort_order" in payload and payload["sort_order"] is not None:
        row.sort_order = int(payload["sort_order"])

    row.updated_at = _utcnow_naive()
    await db.commit()
    await db.refresh(row)
    return TipCategoryDetailResponse(data=await _to_item(row))


@router.delete("/{category_id}")
async def delete_tip_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await db.get(TipCategory, category_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tip category not found")

    row.deleted_at = _utcnow_naive()
    row.updated_at = _utcnow_naive()
    await db.commit()
    return {"success": True}
