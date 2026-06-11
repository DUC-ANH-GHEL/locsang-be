from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.public_product import (
    CreateProductReviewBody,
    CreateProductBody,
    ListProductsResponse,
    ProductDetailResponse,
    ProductReviewItem,
    ProductReviewsResponse,
    ProductReviewSummary,
    PublicProductDetail,
    PublicProductItem,
    UpdateProductBody,
)
from app.core.deps import get_db
from app.domain.models.category import Category
from app.domain.models.order import Order, OrderStatus
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductImage, ProductVariant
from app.domain.models.product_review import ProductReview


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
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return None

    if isinstance(v, str):
        text = v.strip()
        if text == "":
            return None

        # Keep only numeric tokens and separators, remove currency labels/symbols.
        cleaned = re.sub(r"[^0-9,\.\-]", "", text)
        if cleaned in {"", "-", ".", ","}:
            return None

        if "," in cleaned and "." in cleaned:
            # Decide decimal separator by the rightmost symbol.
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if len(parts) == 2 and len(parts[-1]) <= 2:
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "." in cleaned:
            parts = cleaned.split(".")
            if len(parts) > 2:
                cleaned = "".join(parts)
            elif len(parts) == 2 and len(parts[-1]) > 2:
                cleaned = "".join(parts)

    try:
        return float(cleaned if isinstance(v, str) else v)
    except Exception:
        return None


def _to_int(v, default: Optional[int] = None) -> Optional[int]:
    if v is None:
        return default
    if isinstance(v, str) and v.strip() == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


def _datetime_sort_key(value) -> str:
    if value is None:
        return ""
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _reviews_to_summary(reviews: list[ProductReview]) -> ProductReviewSummary:
    active = [r for r in (reviews or []) if bool(getattr(r, "is_active", True))]
    count = len(active)
    if count == 0:
        return ProductReviewSummary(average=0.0, count=0, breakdown={"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})

    total = sum(int(getattr(r, "rating", 0) or 0) for r in active)
    breakdown = {str(i): 0 for i in range(1, 6)}
    for r in active:
        rating = int(getattr(r, "rating", 0) or 0)
        if 1 <= rating <= 5:
            breakdown[str(rating)] += 1

    average = round(total / count, 2)
    return ProductReviewSummary(average=average, count=count, breakdown=breakdown)


def _review_to_item(review: ProductReview) -> ProductReviewItem:
    rating_raw = _to_int(getattr(review, "rating", None))
    rating = 0 if rating_raw is None else max(1, min(5, rating_raw))
    created_at = getattr(review, "created_at", None) or getattr(review, "updated_at", None) or datetime.now(timezone.utc)

    return ProductReviewItem(
        id=str(review.id),
        reviewerName=str(getattr(review, "reviewer_name", None) or "Khach hang"),
        rating=rating,
        comment=review.comment,
        isVerifiedPurchase=bool(getattr(review, "is_verified_purchase", False)),
        createdAt=created_at,
    )


def _extract_variant_attribute_map(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}

    fields = payload.get("fields")
    if not isinstance(fields, list):
        return {}

    out: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        value = str(field.get("value") or "").strip()
        if not name or not value:
            continue
        out[name] = value
    return out


def _build_variant_name(attribute_values: dict[str, str], fallback_sku: Optional[str]) -> str:
    values = [str(v).strip() for v in (attribute_values or {}).values() if str(v).strip()]
    if values:
        return " / ".join(values)
    return str(fallback_sku or "")


def _extract_variant_media(payload: object, image_url: Optional[str]) -> tuple[list[str], list[str]]:
    media_urls: list[str] = []
    video_urls: list[str] = []
    seen_media: set[str] = set()
    seen_videos: set[str] = set()

    def _push_media(value: Optional[str]) -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen_media:
            return
        seen_media.add(normalized)
        media_urls.append(normalized)

    def _push_video(value: Optional[str]) -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen_videos:
            return
        seen_videos.add(normalized)
        video_urls.append(normalized)

    _push_media(image_url)

    if isinstance(payload, dict):
        images = payload.get("images")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str):
                    _push_media(item)
                elif isinstance(item, dict):
                    _push_media(item.get("url") or item.get("image_url"))

        videos = payload.get("videos")
        if isinstance(videos, list):
            for item in videos:
                if isinstance(item, str):
                    _push_video(item)
                elif isinstance(item, dict):
                    _push_video(item.get("url") or item.get("video_url"))

        _push_video(payload.get("video_url"))

    return media_urls, video_urls


def _is_placeholder_like_image(value: Optional[str]) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return (
        "logo_d2wmlf" in text
        or "/api/placeholder/" in text
        or "placeholder.com" in text
    )


def _resolve_storefront_thumbnail(product: Product) -> Optional[str]:
    preferred: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()

    def _push(value: Optional[str]) -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        if _is_placeholder_like_image(normalized):
            fallback.append(normalized)
            return
        preferred.append(normalized)

    # Product images are primary source for storefront cards.
    for img in sorted(product.images or [], key=lambda x: (x.sort_order or 0, x.id)):
        if getattr(img, "type", "image") != "image":
            continue
        _push(getattr(img, "url", None))

    _push(getattr(product, "thumbnail", None))

    # Variant images/media are fallback if product image list is empty.
    for variant in sorted(product.variants or [], key=lambda x: x.id):
        _push(getattr(variant, "image_url", None))

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def _is_variant_active(variant: ProductVariant) -> bool:
    return bool(getattr(variant, "is_active", True)) and str(getattr(variant, "status", "active") or "active") == "active"


def _active_variants(product: Product) -> list[ProductVariant]:
    return [variant for variant in (product.variants or []) if _is_variant_active(variant)]


def _variant_can_purchase(variant: ProductVariant) -> bool:
    manage_stock = bool(getattr(variant, "manage_stock", True))
    if not manage_stock:
        return True
    return int(getattr(variant, "stock", 0) or 0) > 0 or bool(getattr(variant, "allow_backorder", False))


def _product_purchase_state(product: Product) -> dict[str, object]:
    all_variants = list(product.variants or [])
    variants = _active_variants(product)
    if all_variants:
        stock = int(sum(int(getattr(variant, "stock", 0) or 0) for variant in variants))
        allow_backorder = any(bool(getattr(variant, "allow_backorder", False)) for variant in variants)
        can_purchase = any(_variant_can_purchase(variant) for variant in variants)
    else:
        stock = int(_to_int(getattr(product, "stock", None)) or 0)
        allow_backorder = False
        can_purchase = stock > 0

    if stock > 0:
        stock_status = "in_stock"
    elif allow_backorder and can_purchase:
        stock_status = "backorder"
    else:
        stock_status = "out"

    return {
        "stock": stock,
        "allow_backorder": allow_backorder,
        "can_purchase": can_purchase,
        "stock_status": stock_status,
    }


def _product_to_item(
    product: Product,
    category: Category,
    rating_summary: Optional[ProductReviewSummary] = None,
) -> PublicProductItem:
    thumbnail = _resolve_storefront_thumbnail(product)
    created_at = getattr(product, "created_at", None) or datetime.now(timezone.utc)
    updated_at = getattr(product, "updated_at", None) or created_at
    purchase_state = _product_purchase_state(product)

    return PublicProductItem(
        id=str(product.id),
        name=str(getattr(product, "name", None) or f"Product {product.id}"),
        slug=str(getattr(product, "slug", None) or f"product-{product.id}"),
        price=float(_to_float(getattr(product, "price", None)) or 0.0),
        originalPrice=_to_float(getattr(product, "original_price", None)),
        salePrice=_to_float(getattr(product, "sale_price", None)),
        thumbnail=thumbnail,
        stock=int(purchase_state["stock"]),
        allowBackorder=bool(purchase_state["allow_backorder"]),
        canPurchase=bool(purchase_state["can_purchase"]),
        stockStatus=str(purchase_state["stock_status"]),
        status=_normalize_status(product),
        category={"id": str(category.id), "name": str(getattr(category, "name", None) or "Danh muc")},
        ratingSummary=(rating_summary or ProductReviewSummary()).model_dump(),
        createdAt=created_at,
        updatedAt=updated_at,
    )


def _product_to_detail(
    product: Product,
    category: Category,
) -> PublicProductDetail:
    images = []
    for img in sorted(product.images or [], key=lambda x: (x.sort_order or 0, x.id)):
        if getattr(img, "type", "image") != "image":
            continue
        url = str(getattr(img, "url", None) or "").strip()
        if not url:
            continue
        images.append(
            {
                "id": str(img.id),
                "url": url,
                "isPrimary": bool(getattr(img, "is_primary", False)),
                "altText": getattr(img, "alt_text", None),
            }
        )

    variants = []
    for v in sorted(product.variants or [], key=lambda x: x.id):
        payload: dict[str, Any] = {}
        fallback_attr_values = {
            k: str(val)
            for k, val in {
                "Size": getattr(v, "size", None),
                "Color": getattr(v, "color", None),
                "Material": getattr(v, "material", None),
            }.items()
            if val is not None and str(val).strip() != ""
        }
        attribute_values = _extract_variant_attribute_map(payload) or fallback_attr_values
        media_urls, video_urls = _extract_variant_media(payload, getattr(v, "image_url", None))
        dimension_text = None
        if isinstance(payload, dict):
            dimension_text = str(payload.get("dimension_text") or payload.get("dimension") or "").strip() or None

        variants.append(
            {
                "id": str(v.id),
                "sku": str(getattr(v, "sku", None) or f"VAR-{v.id}"),
                "size": getattr(v, "size", None),
                "color": getattr(v, "color", None),
                "material": getattr(v, "material", None),
                "price": _to_float(getattr(v, "price", None)),
                "salePrice": _to_float(getattr(v, "sale_price", None)),
                "comparePrice": _to_float(getattr(v, "compare_price", None)),
                "costPrice": _to_float(getattr(v, "cost_price", None)),
                "stock": int(getattr(v, "stock", 0) or 0),
                "manageStock": bool(getattr(v, "manage_stock", True)),
                "allowBackorder": bool(getattr(v, "allow_backorder", False)),
                "canPurchase": _is_variant_active(v) and _variant_can_purchase(v),
                "status": str(getattr(v, "status", "active") or "active"),
                "isActive": bool(getattr(v, "is_active", True)),
                "imageUrl": getattr(v, "image_url", None),
                "attributeValues": attribute_values,
                "variantName": _build_variant_name(attribute_values, getattr(v, "sku", None)),
                "mediaUrls": media_urls,
                "videoUrls": video_urls,
                "weightGram": _to_float(payload.get("weight") if isinstance(payload, dict) else None),
                "dimensionText": dimension_text,
            }
        )

    tags_raw = getattr(product, "tags", None)
    if isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw if t is not None]
    elif isinstance(tags_raw, str) and tags_raw.strip() != "":
        tags = [tags_raw.strip()]
    else:
        tags = []

    specifications = []
    specs_raw = getattr(product, "specifications", None)
    if isinstance(specs_raw, list):
        for item in specs_raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("key") or item.get("name") or "").strip()
            value = str(item.get("value") or "").strip()
            if label and value:
                specifications.append({"label": label, "value": value})

    review_entities = [
        r
        for r in sorted(
            product.reviews or [],
            key=lambda x: _datetime_sort_key(getattr(x, "created_at", None) or getattr(x, "updated_at", None)),
            reverse=True,
        )
        if bool(getattr(r, "is_active", True))
    ]
    review_items = [_review_to_item(r) for r in review_entities]
    summary = _reviews_to_summary(review_entities)

    detail_base = _product_to_item(product, category).model_dump(by_alias=True)
    detail_base["ratingSummary"] = summary.model_dump()
    detail_base["salePrice"] = _to_float(getattr(product, "sale_price", None))

    return PublicProductDetail(
        **detail_base,
        shortDescription=getattr(product, "short_description", None),
        description=getattr(product, "description", None),
        currency=getattr(product, "currency", "VND"),
        sku=getattr(product, "sku", None),
        affiliate=_to_int(getattr(product, "affiliate", None)),
        brand=getattr(product, "brand", None),
        material=getattr(product, "material", None),
        size=getattr(product, "size", None),
        color=getattr(product, "color", None),
        petType=getattr(product, "pet_type", None),
        season=getattr(product, "season", None),
        weight=_to_float(getattr(product, "weight", None)),
        length=_to_float(getattr(product, "length", None)),
        width=_to_float(getattr(product, "width", None)),
        height=_to_float(getattr(product, "height", None)),
        hasVariants=bool(getattr(product, "has_variants", False)),
        featured=bool(getattr(product, "featured", False)),
        tags=tags,
        specifications=specifications,
        images=images,
        variants=variants,
        comboOffers=[],
        promotionOffers=[],
        reviews=[r.model_dump(by_alias=True) for r in review_items],
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
    purchasable: Optional[str] = Query("true"),
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
        purchasable_only = str(purchasable or "true").strip().lower() not in ("0", "false", "no", "all")

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
        if purchasable_only:
            purchasable_variant_exists = (
                select(ProductVariant.id)
                .where(
                    ProductVariant.product_id == Product.id,
                    ProductVariant.is_active.is_(True),
                    ProductVariant.status == "active",
                    or_(
                        ProductVariant.manage_stock.is_(False),
                        ProductVariant.stock > 0,
                        ProductVariant.allow_backorder.is_(True),
                    ),
                )
                .exists()
            )
            any_variant_exists = select(ProductVariant.id).where(ProductVariant.product_id == Product.id).exists()
            filters.append(
                or_(
                    purchasable_variant_exists,
                    and_(~any_variant_exists, Product.stock > 0),
                )
            )

        sort_map = {
            "createdAt": Product.created_at,
            "price": Product.price,
            "name": Product.name,
        }
        sort_col = sort_map[sortBy]
        order_by = sort_col.asc() if order == "asc" else sort_col.desc()

        base_stmt = (
            select(Product, Category)
            .join(Category, Product.category_id == Category.id)
            .options(selectinload(Product.images), selectinload(Product.variants))
        )
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

        product_ids = [int(prod.id) for prod, _cat in rows if getattr(prod, "id", None) is not None]
        summary_by_product_id: dict[int, ProductReviewSummary] = {
            pid: ProductReviewSummary(average=0.0, count=0, breakdown={"1": 0, "2": 0, "3": 0, "4": 0, "5": 0})
            for pid in product_ids
        }

        if product_ids:
            agg_stmt = (
                select(
                    ProductReview.product_id,
                    func.avg(ProductReview.rating),
                    func.count(ProductReview.id),
                )
                .where(
                    ProductReview.product_id.in_(product_ids),
                    ProductReview.is_active.is_(True),
                )
                .group_by(ProductReview.product_id)
            )
            agg_rows = (await db.execute(agg_stmt)).all()

            for product_id, avg_raw, count_raw in agg_rows:
                pid = int(product_id)
                summary = summary_by_product_id.get(pid)
                if not summary:
                    continue
                summary.average = round(float(avg_raw or 0), 2)
                summary.count = int(count_raw or 0)

            breakdown_stmt = (
                select(
                    ProductReview.product_id,
                    ProductReview.rating,
                    func.count(ProductReview.id),
                )
                .where(
                    ProductReview.product_id.in_(product_ids),
                    ProductReview.is_active.is_(True),
                )
                .group_by(ProductReview.product_id, ProductReview.rating)
            )
            breakdown_rows = (await db.execute(breakdown_stmt)).all()

            for product_id, rating_raw, count_raw in breakdown_rows:
                pid = int(product_id)
                rating_i = int(rating_raw or 0)
                if rating_i < 1 or rating_i > 5:
                    continue
                summary = summary_by_product_id.get(pid)
                if not summary:
                    continue
                summary.breakdown[str(rating_i)] = int(count_raw or 0)

        items = [
            _product_to_item(
                prod,
                cat,
                summary_by_product_id.get(int(prod.id)) if getattr(prod, "id", None) is not None else None,
            )
            for prod, cat in rows
        ]

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
        .options(selectinload(Product.images), selectinload(Product.variants), selectinload(Product.reviews))
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
            .options(selectinload(Product.images), selectinload(Product.variants), selectinload(Product.reviews))
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
            .options(selectinload(Product.images), selectinload(Product.variants), selectinload(Product.reviews))
            .where(Product.id == product_id)
            .limit(1)
        )
    ).scalar_one()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    detail = _product_to_detail(product, category)
    return {"success": True, "data": detail.model_dump(by_alias=True)}


@router.get("/{id}/reviews", response_model=ProductReviewsResponse)
async def list_product_reviews(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.reviews))
            .where(Product.id == product_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    review_entities = [r for r in sorted(product.reviews or [], key=lambda x: x.created_at, reverse=True) if bool(getattr(r, "is_active", True))]
    review_items = [_review_to_item(r) for r in review_entities]
    summary = _reviews_to_summary(review_entities)

    return {
        "success": True,
        "data": [r.model_dump(by_alias=True) for r in review_items],
        "summary": summary.model_dump(),
    }


@router.post("/{id}/reviews", response_model=ProductReviewsResponse, status_code=status.HTTP_201_CREATED)
async def create_product_review(
    id: str,
    body: CreateProductReviewBody,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    requested_phone = ''.join(ch for ch in str(body.phone or '') if ch.isdigit() or ch == '+')
    tracking_code = str(body.tracking_code or '').strip()
    if not tracking_code:
        raise HTTPException(status_code=400, detail='trackingCode is required')

    eligible_order_stmt = (
        select(Order.id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.deleted_at.is_(None),
            Order.status.in_([OrderStatus.PROCESSING.value, OrderStatus.SHIPPED.value, OrderStatus.DELIVERED.value]),
            Order.tracking_code == tracking_code,
            Order.receiver_phone == requested_phone,
            OrderItem.product_id == product_id,
        )
        .limit(1)
    )
    eligible_order_id = (await db.execute(eligible_order_stmt)).scalar_one_or_none()
    if eligible_order_id is None:
        raise HTTPException(
            status_code=403,
            detail='Chỉ khách đã mua sản phẩm và nhận hàng mới được đánh giá',
        )

    review = ProductReview(
        product_id=product_id,
        reviewer_name=body.reviewer_name.strip(),
        rating=int(body.rating),
        comment=(body.comment.strip() if body.comment else None),
        is_verified_purchase=True,
        is_active=True,
    )
    db.add(review)
    await db.commit()

    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.reviews))
            .where(Product.id == product_id)
            .limit(1)
        )
    ).scalar_one()

    review_entities = [r for r in sorted(product.reviews or [], key=lambda x: x.created_at, reverse=True) if bool(getattr(r, "is_active", True))]
    review_items = [_review_to_item(r) for r in review_entities]
    summary = _reviews_to_summary(review_entities)

    return {
        "success": True,
        "data": [r.model_dump(by_alias=True) for r in review_items],
        "summary": summary.model_dump(),
    }


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
