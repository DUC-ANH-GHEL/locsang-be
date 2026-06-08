from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.domain.models.customer_story import CustomerStory


router = APIRouter(prefix="/customer-stories", tags=["Public Customer Stories"])


@router.get("")
async def list_public_customer_stories(
    limit: int = 12,
    db: AsyncSession = Depends(get_db),
):
    safe_limit = max(1, min(20, int(limit or 12)))
    rows = (
        await db.execute(
            select(CustomerStory)
            .where(
                CustomerStory.deleted_at.is_(None),
                CustomerStory.is_active.is_(True),
            )
            .order_by(CustomerStory.is_featured.desc(), CustomerStory.sort_order.asc(), CustomerStory.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()

    return {
        "success": True,
        "data": [
            {
                "id": row.id,
                "customer_name": row.customer_name,
                "pet_name": row.pet_name,
                "customer_title": row.customer_title,
                "quote": row.quote,
                "rating": max(1, min(5, int(row.rating or 5))),
                "image_url": row.image_url,
                "is_featured": bool(row.is_featured),
            }
            for row in rows
        ],
    }
