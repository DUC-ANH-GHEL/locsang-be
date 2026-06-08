from __future__ import annotations

from datetime import datetime
from html import escape
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.domain.models.tip_post import TipPost


router = APIRouter(prefix="/tips", tags=["Public Tips"])


def _now_utc() -> datetime:
    return datetime.utcnow()


async def _publish_due_posts(db: AsyncSession) -> None:
    now = _now_utc()
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


def _serialize_tip(row: TipPost, with_content: bool = False) -> dict:
    data = {
        "id": row.id,
        "title": row.title,
        "slug": row.slug,
        "excerpt": row.excerpt,
        "template_key": row.template_key,
        "content_blocks": row.content_blocks or [],
        "featured_image": row.featured_image,
        "category": row.category,
        "tags": [str(x) for x in (row.tags or []) if str(x).strip()],
        "status": row.status,
        "featured": bool(row.featured),
        "seo_title": row.seo_title,
        "seo_description": row.seo_description,
        "published_at": row.published_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if with_content:
        data["content"] = row.content
    return data


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(text or ""))).strip()


async def _find_public_tip(db: AsyncSession, slug: str) -> Optional[TipPost]:
    row = (
        await db.execute(
            select(TipPost).where(
                TipPost.slug == slug,
                TipPost.deleted_at.is_(None),
                TipPost.status == "published",
                (TipPost.published_at.is_(None)) | (TipPost.published_at <= _now_utc()),
            )
        )
    ).scalar_one_or_none()

    if row is None and slug.isdigit():
        row = (
            await db.execute(
                select(TipPost).where(
                    TipPost.id == int(slug),
                    TipPost.deleted_at.is_(None),
                    TipPost.status == "published",
                    (TipPost.published_at.is_(None)) | (TipPost.published_at <= _now_utc()),
                )
            )
        ).scalar_one_or_none()

    return row


@router.get("")
async def list_public_tips(
    page: int = Query(1, ge=1),
    limit: int = Query(9, ge=1, le=50),
    search: Optional[str] = None,
    category: Optional[str] = None,
    featured: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    await _publish_due_posts(db)

    filters = [
        TipPost.deleted_at.is_(None),
        TipPost.status == "published",
        (TipPost.published_at.is_(None)) | (TipPost.published_at <= _now_utc()),
    ]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append((TipPost.title.ilike(q)) | (TipPost.excerpt.ilike(q)) | (TipPost.content.ilike(q)))

    if category and category.strip():
        filters.append(TipPost.category == category.strip())

    if featured is not None:
        filters.append(TipPost.featured.is_(featured))

    total_stmt = select(func.count()).select_from(TipPost).where(*filters)
    total = int((await db.execute(total_stmt)).scalar_one())

    offset = (page - 1) * limit
    rows = (
        await db.execute(
            select(TipPost)
            .where(*filters)
            .order_by(TipPost.featured.desc(), TipPost.published_at.desc().nullslast(), TipPost.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    categories_rows = (
        await db.execute(
            select(TipPost.category)
            .where(
                TipPost.deleted_at.is_(None),
                TipPost.status == "published",
                TipPost.category.is_not(None),
            )
            .group_by(TipPost.category)
            .order_by(TipPost.category.asc())
        )
    ).scalars().all()
    categories = [str(x) for x in categories_rows if str(x or "").strip()]

    return {
        "success": True,
        "data": [_serialize_tip(row, with_content=False) for row in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
            "has_next": (page * limit) < total,
            "has_prev": page > 1,
        },
        "filters": {
            "categories": categories,
        },
    }


@router.get("/{slug}")
async def get_public_tip_detail(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    await _publish_due_posts(db)

    row = await _find_public_tip(db, slug)

    if not row:
        raise HTTPException(status_code=404, detail="Tip not found")

    related = (
        await db.execute(
            select(TipPost)
            .where(
                TipPost.id != row.id,
                TipPost.deleted_at.is_(None),
                TipPost.status == "published",
                (TipPost.published_at.is_(None)) | (TipPost.published_at <= _now_utc()),
                TipPost.category == row.category if row.category else True,
            )
            .order_by(TipPost.featured.desc(), TipPost.published_at.desc().nullslast(), TipPost.created_at.desc())
            .limit(4)
        )
    ).scalars().all()

    return {
        "success": True,
        "data": _serialize_tip(row, with_content=True),
        "related": [_serialize_tip(item, with_content=False) for item in related],
    }


@router.api_route("/{slug}/share", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def share_public_tip(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _publish_due_posts(db)

    row = await _find_public_tip(db, slug)
    if not row:
        raise HTTPException(status_code=404, detail="Tip not found")

    frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")
    tip_slug = row.slug or slug
    article_url = f"{frontend_base}/tips/{tip_slug}"
    share_url = f"{frontend_base}/share/tips/{tip_slug}"
    share_version = str(request.query_params.get("v") or "").strip()
    if share_version.isdigit():
        share_url = f"{share_url}?v={share_version}"
    title = (row.seo_title or row.title or "Cam nang mua sam").strip()
    description = (
        row.seo_description
        or row.excerpt
        or _strip_html(row.content or "")
        or "Doc bai viet cam nang mua sam huu ich tu Lộc Sang."
    ).strip()
    description = description[:220]
    image_url = (row.featured_image or "https://res.cloudinary.com/diwxfpt92/image/upload/v1770981822/logo_d2wmlf.png").strip()

    safe_title = escape(title)
    safe_description = escape(description)
    safe_article_url = escape(article_url)
    safe_share_url = escape(share_url)
    safe_image_url = escape(image_url)

    html = f"""<!doctype html>
<html lang=\"vi\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <meta name=\"language\" content=\"vi\" />
        <meta http-equiv=\"content-language\" content=\"vi-VN\" />
        <title>{safe_title} | Lộc Sang</title>
        <meta name=\"description\" content=\"{safe_description}\" />
        <meta property=\"og:site_name\" content=\"Lộc Sang\" />
        <meta property=\"og:locale\" content=\"vi_VN\" />
        <meta property=\"og:type\" content=\"article\" />
        <meta property=\"og:title\" content=\"{safe_title}\" />
        <meta property=\"og:description\" content=\"{safe_description}\" />
        <meta property=\"og:image\" content=\"{safe_image_url}\" />
        <meta property=\"og:image:secure_url\" content=\"{safe_image_url}\" />
        <meta property=\"og:image:alt\" content=\"{safe_title}\" />
                <meta property=\"og:url\" content=\"{safe_share_url}\" />
        <meta name=\"twitter:card\" content=\"summary_large_image\" />
        <meta name=\"twitter:title\" content=\"{safe_title}\" />
        <meta name=\"twitter:description\" content=\"{safe_description}\" />
        <meta name=\"twitter:image\" content=\"{safe_image_url}\" />
                <link rel=\"canonical\" href=\"{safe_share_url}\" />
    </head>
    <body>
        <p>Mo bai viet tai Lộc Sang.</p>
        <p><a href=\"{safe_article_url}\">Xem bai viet</a></p>
    </body>
</html>"""

    return HTMLResponse(
        content=html,
        status_code=200,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
