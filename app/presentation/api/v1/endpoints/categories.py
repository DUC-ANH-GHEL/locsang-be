from typing import List

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.application.dto.category import CategoryCreate, CategoryUpdate, CategoryResponse
from app.domain.models.category import Category
from app.infrastructure.repositories.category_repository import CategoryRepository

router = APIRouter(prefix="/categories", tags=["categories"])


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"[\s-]+", "-", value)
    return value.strip("-") or "category"

@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    category: CategoryCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new category."""
    repository = CategoryRepository(db)
    existing = await repository.get_by_name(category.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Category name already exists",
        )

    base_slug = _slugify(category.name)
    slug = base_slug
    suffix = 2
    while True:
        existing_slug = await db.execute(select(Category).where(Category.slug == slug))
        if existing_slug.scalar_one_or_none() is None:
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    entity = Category(**category.model_dump(), slug=slug)
    return await repository.create(entity)

@router.get("/", response_model=List[CategoryResponse])
async def get_categories(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Get all categories."""
    result = await db.execute(select(Category).offset(skip).limit(limit))
    return list(result.scalars().all())

@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a category by ID."""
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    return category

@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    category: CategoryUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a category."""
    entity = await db.get(Category, category_id)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    update_data = category.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entity, field, value)

    await db.commit()
    await db.refresh(entity)
    return entity

@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a category."""
    entity = await db.get(Category, category_id)
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    await db.delete(entity)
    await db.commit()
