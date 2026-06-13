from typing import List

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.category import CategoryResponse
from app.core.database import get_db
from app.domain.models.category import Category
from app.presentation.api.public_api.cache import apply_public_cache


router = APIRouter(prefix="/categories", tags=["Public Categories"])


@router.get("", response_model=List[CategoryResponse])
async def get_public_categories(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    apply_public_cache(response)
    result = await db.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
