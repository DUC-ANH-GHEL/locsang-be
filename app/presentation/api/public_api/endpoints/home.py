from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_db
from app.domain.models.category import Category
from app.domain.models.home_content import HomeContent
from app.domain.models.order import Order
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductVariant
from app.presentation.api.public_api.cache import apply_public_cache
from app.presentation.api.public_api.endpoints.home_content import _default_home_payload
from app.presentation.api.public_api.endpoints.products import (
    _product_to_item,
    _sellable_product_filters,
)


router = APIRouter(tags=["Public Home"])


def _dump_product(product: Product, category: Category, sold_count: int = 0) -> dict[str, Any]:
    setattr(product, "_sold_count", int(sold_count or 0))
    return _product_to_item(product, category).model_dump(by_alias=True)


async def _get_home_content(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(HomeContent).limit(1))).scalar_one_or_none()
    defaults = _default_home_payload()
    if not row:
        return {"content": defaults, "published_at": None}
    return {"content": {**defaults, **(row.published_content or {})}, "published_at": row.published_at}


async def _get_categories_with_products(db: AsyncSession) -> list[dict[str, Any]]:
    stmt = (
        select(Product, Category)
        .join(Category, Product.category_id == Category.id)
        .options(selectinload(Product.images), selectinload(Product.variants))
        .where(Category.is_active.is_(True), *_sellable_product_filters())
        .order_by(Category.id.asc(), Product.created_at.desc())
        .limit(60)
    )
    rows = (await db.execute(stmt)).all()

    grouped: dict[int, dict[str, Any]] = {}
    for product, category in rows:
        bucket = grouped.setdefault(
            category.id,
            {
                "id": str(category.id),
                "name": str(category.name or ""),
                "slug": str(category.slug or category.id),
                "description": category.description,
                "image": category.image,
                "products": [],
            },
        )
        if len(bucket["products"]) < 4:
            bucket["products"].append(_dump_product(product, category))

    return list(grouped.values())[:8]


async def _get_best_sellers(db: AsyncSession) -> list[dict[str, Any]]:
    sold_count = func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_count")
    stmt = (
        select(Product, Category, sold_count)
        .join(Category, Product.category_id == Category.id)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .options(selectinload(Product.images), selectinload(Product.variants))
        .where(
            Category.is_active.is_(True),
            Order.deleted_at.is_(None),
            Order.status != "cancelled",
            *_sellable_product_filters(),
        )
        .group_by(Product.id, Category.id)
        .order_by(sold_count.desc(), Product.created_at.desc())
        .limit(8)
    )
    return [_dump_product(product, category, sold) for product, category, sold in (await db.execute(stmt)).all()]


async def _get_sale_products(db: AsyncSession) -> list[dict[str, Any]]:
    any_variant_exists = select(ProductVariant.id).where(ProductVariant.product_id == Product.id).exists()
    sale_variant_exists = (
        select(ProductVariant.id)
        .where(
            ProductVariant.product_id == Product.id,
            ProductVariant.is_active.is_(True),
            ProductVariant.status == "active",
            ProductVariant.sale_price.is_not(None),
            ProductVariant.sale_price > 0,
            ProductVariant.price.is_not(None),
            ProductVariant.sale_price < ProductVariant.price,
            or_(
                ProductVariant.manage_stock.is_(False),
                ProductVariant.stock > 0,
                ProductVariant.allow_backorder.is_(True),
            ),
        )
        .exists()
    )
    stmt = (
        select(Product, Category)
        .join(Category, Product.category_id == Category.id)
        .options(selectinload(Product.images), selectinload(Product.variants))
        .where(
            Category.is_active.is_(True),
            or_(
                sale_variant_exists,
                and_(
                    ~any_variant_exists,
                    Product.sale_price.is_not(None),
                    Product.sale_price > 0,
                    Product.sale_price < Product.price,
                ),
            ),
            *_sellable_product_filters(),
        )
        .order_by(Product.updated_at.desc(), Product.created_at.desc())
        .limit(8)
    )
    return [_dump_product(product, category) for product, category in (await db.execute(stmt)).all()]


@router.get("/home")
async def get_home(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    apply_public_cache(response)
    return {
        "home_content": await _get_home_content(db),
        "categories_with_products": await _get_categories_with_products(db),
        "best_sellers": await _get_best_sellers(db),
        "sale_products": await _get_sale_products(db),
    }
