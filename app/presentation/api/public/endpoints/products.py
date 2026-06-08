from __future__ import annotations

import re
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.public_product import (
    CreateProductBody,
    ListProductsResponse,
    ProductDetailResponse,
    PublicProductDetail,
    PublicProductItem,
    UpdateProductBody,
)
from app.core.deps import get_db
from app.domain.models.category import Category
from app.domain.models.product import Product, ProductImage


router = APIRouter(prefix="/products", tags=["Public Products"])


_id_prefix_re = re.compile(r"^(?:cat|prod)_(\d+)$", re.IGNORECASE)


def _parse_int_id(raw: Optional[str], field: str) -> Optional[int]:
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except Exception:
        m = _id_prefix_re.match(raw)
        if m:
            return int(m.group(1))
        raise HTTPException(status_code=400, detail=f"{field} must be an integer string")


_slug_invalid_re = re.compile(r"[^a-z0-9\-]+")


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = _slug_invalid_re.sub("", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "product"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    candidate = base
    suffix = 2
    while True:
        exists = await db.execute(select(Product.id).where(Product.slug == candidate).limit(1))
        if exists.first() is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def _unique_sku(db: AsyncSession) -> str:
    # DB requires sku NOT NULL; generate a unique SKU.
    while True:
        sku = f"SKU-{uuid4().hex[:10].upper()}"
        exists = await db.execute(select(Product.id).where(Product.sku == sku).limit(1))
        if exists.first() is None:
            return sku


def _status_to_is_active(status_str: str) -> bool:
    return status_str == "active"


def _is_active_to_status(is_active: bool) -> str:
    return "active" if is_active else "inactive"


def _normalize_status(product: Product) -> str:
    s = getattr(product, "status", None)
    if s in ("active", "inactive"):
        return s
    return _is_active_to_status(bool(getattr(product, "is_active", True)))


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _product_to_item(product: Product, category: Category) -> PublicProductItem:
    return PublicProductItem(
        id=str(product.id),
        name=product.name,
        slug=product.slug,
        price=float(product.price),
        originalPrice=_to_float(getattr(product, "original_price", None)),
        thumbnail=getattr(product, "thumbnail", None),
        stock=int(product.stock or 0),
        status=_normalize_status(product),
        category={"id": str(category.id), "name": category.name},
        createdAt=product.created_at,
        updatedAt=product.updated_at,
    )


def _product_to_detail(product: Product, category: Category) -> PublicProductDetail:
    images = [
        {"id": str(img.id), "url": img.url}
        for img in sorted(product.images or [], key=lambda x: (x.sort_order or 0, x.id))
        if getattr(img, "type", "image") == "image"
    ]
    return PublicProductDetail(
        **_product_to_item(product, category).model_dump(by_alias=True),
        images=images,
    )


@router.get("", response_model=ListProductsResponse)
async def list_products(
    page: Optional[str] = Query("1"),
    limit: Optional[str] = Query("20"),
    search: Optional[str] = None,
    categoryId: Optional[str] = None,
    minPrice: Optional[str] = None,
    maxPrice: Optional[str] = None,
    status_q: Optional[str] = Query("active", alias="status"),
    sortBy: Optional[str] = Query("createdAt"),
    order: Optional[str] = Query("desc"),
    db: AsyncSession = Depends(get_db),
):
    try:
        page_i = int(page or 1)
        limit_i = int(limit or 20)
        if page_i < 1:
            raise ValueError("page")
        if limit_i < 1 or limit_i > 100:
            raise ValueError("limit")

        min_price_f = float(minPrice) if (minPrice is not None and str(minPrice).strip() != "") else None
        max_price_f = float(maxPrice) if (maxPrice is not None and str(maxPrice).strip() != "") else None
        if min_price_f is not None and max_price_f is not None and min_price_f > max_price_f:
            raise ValueError("minPrice")

        sortBy = sortBy or "createdAt"
        order = order or "desc"
        status_q = status_q or "active"
        if sortBy not in ("createdAt", "price", "name"):
            raise ValueError("sortBy")
        if order not in ("asc", "desc"):
            raise ValueError("order")
        if status_q not in ("active", "inactive"):
            raise ValueError("status")

        category_id = _parse_int_id(categoryId, "categoryId")

        filters = []
        if search and search.strip() != "":
            filters.append(Product.name.ilike(f"%{search.strip()}%"))
        if category_id is not None:
            filters.append(Product.category_id == category_id)
        if min_price_f is not None:
            filters.append(Product.price >= float(min_price_f))
        if max_price_f is not None:
            filters.append(Product.price <= float(max_price_f))

        # Hard safety guard for storefront visibility.
        filters.append(Product.deleted_at.is_(None))
        filters.append(Product.is_active.is_(True))

        # status filter: spec requires `status`
        filters.append(Product.status == status_q)

        sort_map = {
            "createdAt": Product.created_at,
            "price": Product.price,
            "name": Product.name,
        }
        sort_col = sort_map[sortBy]
        order_by = sort_col.asc() if order == "asc" else sort_col.desc()

        base_stmt = select(Product, Category).join(Category, Product.category_id == Category.id)
        if filters:
            base_stmt = base_stmt.where(*filters)

        count_stmt = select(func.count()).select_from(Product).join(Category, Product.category_id == Category.id)
        if filters:
            count_stmt = count_stmt.where(*filters)

        total_items = int((await db.execute(count_stmt)).scalar_one())
        total_pages = (total_items + limit_i - 1) // limit_i if total_items > 0 else 0

        offset = (page_i - 1) * limit_i
        stmt = base_stmt.order_by(order_by).offset(offset).limit(limit_i)

        rows = (await db.execute(stmt)).all()
        items = [_product_to_item(prod, cat) for prod, cat in rows]

        has_next = total_pages > 0 and page_i < total_pages
        has_prev = total_pages > 0 and page_i > 1

        return {
            "success": True,
            "data": [i.model_dump(by_alias=True) for i in items],
            "pagination": {
                "page": page_i,
                "limit": limit_i,
                "totalItems": total_items,
                "totalPages": total_pages,
                "hasNext": has_next,
                "hasPrev": has_prev,
            },
        }
    except HTTPException:
        return JSONResponse(status_code=400, content={"success": False, "message": "Invalid query parameters"})
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "message": "Invalid query parameters"})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "message": "Internal server error"})


@router.get("/{id}", response_model=ProductDetailResponse)
async def get_product_detail(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    stmt = (
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.id == product_id)
        .limit(1)
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    category = await db.get(Category, product.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    detail = _product_to_detail(product, category)
    return {"success": True, "data": detail.model_dump(by_alias=True)}


@router.post("", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: CreateProductBody,
    db: AsyncSession = Depends(get_db),
):
    category_id = _parse_int_id(body.category_id, "categoryId")
    if category_id is None:
        raise HTTPException(status_code=400, detail="categoryId is required")

    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Invalid categoryId")

    slug_base = _slugify(body.name)
    slug = await _unique_slug(db, slug_base)
    sku = await _unique_sku(db)

    product = Product(
        name=body.name,
        slug=slug,
        description=body.description,
        price=float(body.price),
        original_price=_to_float(body.original_price),
        thumbnail=body.thumbnail,
        category_id=category_id,
        stock=int(body.stock or 0),
        is_active=_status_to_is_active(body.status),
        status=body.status,
        sku=sku,
    )

    db.add(product)
    await db.flush()

    for idx, url in enumerate(body.images or []):
        db.add(
            ProductImage(
                product_id=product.id,
                url=url,
                sort_order=idx,
                is_primary=(idx == 0 and not body.thumbnail),
                type="image",
            )
        )

    await db.commit()
    await db.refresh(product)

    # reload images for detail
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id == product.id)
            .limit(1)
        )
    ).scalar_one()

    detail = _product_to_detail(product, category)
    return {"success": True, "data": detail.model_dump(by_alias=True)}


@router.put("/{id}", response_model=ProductDetailResponse)
async def update_product(
    id: str,
    body: UpdateProductBody,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body.category_id is not None:
        category_id = _parse_int_id(body.category_id, "categoryId")
        if category_id is None:
            raise HTTPException(status_code=400, detail="categoryId must be an integer string")
        category = await db.get(Category, category_id)
        if not category:
            raise HTTPException(status_code=400, detail="Invalid categoryId")
        product.category_id = category_id
    else:
        category = await db.get(Category, product.category_id)

    if body.name is not None:
        product.name = body.name
        slug_base = _slugify(body.name)
        product.slug = await _unique_slug(db, slug_base)

    if body.description is not None:
        product.description = body.description
    if body.price is not None:
        product.price = float(body.price)
    if body.original_price is not None:
        product.original_price = _to_float(body.original_price)
    if body.thumbnail is not None:
        product.thumbnail = body.thumbnail
    if body.stock is not None:
        product.stock = int(body.stock)
    if body.status is not None:
        product.is_active = _status_to_is_active(body.status)
        product.status = body.status

    await db.commit()

    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id == product_id)
            .limit(1)
        )
    ).scalar_one()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    detail = _product_to_detail(product, category)
    return {"success": True, "data": detail.model_dump(by_alias=True)}


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def soft_delete_product(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.is_active = False
    product.status = "inactive"
    await db.commit()

    return {"success": True}
