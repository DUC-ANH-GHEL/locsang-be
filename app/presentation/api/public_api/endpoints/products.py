from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select
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
from app.domain.models.order import Order
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductAttribute, ProductImage, ProductVariant, VariantAttributeValue
from app.presentation.api.public_api.cache import apply_public_cache


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
_VIETNAMESE_SEARCH_FROM = "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
_VIETNAMESE_SEARCH_TO = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"


def _normalize_search_token(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.translate(str.maketrans(_VIETNAMESE_SEARCH_FROM, _VIETNAMESE_SEARCH_TO))
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _searchable_expr(column: Any) -> Any:
    return func.translate(func.lower(column), _VIETNAMESE_SEARCH_FROM, _VIETNAMESE_SEARCH_TO)


def _build_product_search_filter(raw_search: str) -> Any:
    tokens = [token for token in re.split(r"[\s,;]+", _normalize_search_token(raw_search)) if token]
    if not tokens:
        return None

    searchable_columns = [_searchable_expr(Product.name)]
    token_filters = []
    for token in tokens[:6]:
        pattern = f"%{token}%"
        token_filters.append(or_(*[column.ilike(pattern) for column in searchable_columns]))
    return and_(*token_filters)


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


def _product_detail_load_options() -> list[Any]:
    return [
        selectinload(Product.images),
        selectinload(Product.variants)
        .selectinload(ProductVariant.attribute_values)
        .selectinload(VariantAttributeValue.attribute),
        selectinload(Product.variants)
        .selectinload(ProductVariant.attribute_values)
        .selectinload(VariantAttributeValue.attribute_value),
        selectinload(Product.attributes).selectinload(ProductAttribute.values),
    ]


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


def _variant_attribute_map(variant: ProductVariant) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in getattr(variant, "attribute_values", None) or []:
        attribute = getattr(item, "attribute", None)
        attribute_value = getattr(item, "attribute_value", None)
        name = str(getattr(attribute, "name", "") or "").strip()
        value = str(getattr(attribute_value, "value", "") or "").strip()
        if name and value:
            out[name] = value
    return out


def _product_variant_attributes(product: Product, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used_values: dict[str, set[str]] = {}
    for variant in variants:
        attr_map = variant.get("attributeValues")
        if not isinstance(attr_map, dict):
            continue
        for name, value in attr_map.items():
            clean_name = str(name or "").strip()
            clean_value = str(value or "").strip()
            if not clean_name or not clean_value:
                continue
            used_values.setdefault(clean_name, set()).add(clean_value)

    if not used_values:
        return []

    ordered: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for attribute in sorted(getattr(product, "attributes", None) or [], key=lambda item: (getattr(item, "id", 0) or 0)):
        name = str(getattr(attribute, "name", "") or "").strip()
        if not name or name not in used_values or name in seen_names:
            continue
        seen_names.add(name)
        values: list[str] = []
        for attr_value in sorted(getattr(attribute, "values", None) or [], key=lambda item: (getattr(item, "id", 0) or 0)):
            value = str(getattr(attr_value, "value", "") or "").strip()
            if value and value in used_values[name] and value not in values:
                values.append(value)
        for value in used_values[name]:
            if value not in values:
                values.append(value)
        if values:
            ordered.append({"name": name, "values": values})

    for name, values in used_values.items():
        if name not in seen_names:
            ordered.append({"name": name, "values": sorted(values)})

    return ordered


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


def _sellable_product_filters() -> list[Any]:
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
    return [
        Product.deleted_at.is_(None),
        Product.is_active.is_(True),
        Product.status == "active",
        or_(
            purchasable_variant_exists,
            and_(~any_variant_exists, Product.stock > 0),
        ),
    ]


def _get_product_sold_count(product: Product) -> int:
    return int(getattr(product, "_sold_count", 0) or 0)


def _product_to_item(product: Product, category: Category) -> PublicProductItem:
    thumbnail = _resolve_storefront_thumbnail(product)
    created_at = getattr(product, "created_at", None) or datetime.now(timezone.utc)
    updated_at = getattr(product, "updated_at", None) or created_at
    purchase_state = _product_purchase_state(product)

    return PublicProductItem(
        id=str(product.id),
        name=str(getattr(product, "name", None) or f"Product {product.id}"),
        slug=str(getattr(product, "slug", None) or f"product-{product.id}"),
        sku=getattr(product, "sku", None),
        price=float(_to_float(getattr(product, "price", None)) or 0.0),
        salePrice=_to_float(getattr(product, "sale_price", None)),
        thumbnail=thumbnail,
        stock=int(purchase_state["stock"]),
        allowBackorder=bool(purchase_state["allow_backorder"]),
        canPurchase=bool(purchase_state["can_purchase"]),
        stockStatus=str(purchase_state["stock_status"]),
        soldCount=_get_product_sold_count(product),
        status=_normalize_status(product),
        category={"id": str(category.id), "name": str(getattr(category, "name", None) or "Danh muc")},
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
        if not _is_variant_active(v):
            continue
        attribute_values = _variant_attribute_map(v)
        payload: dict[str, Any] = {}
        media_urls, video_urls = _extract_variant_media(payload, getattr(v, "image_url", None))

        variants.append(
            {
                "id": str(v.id),
                "sku": str(getattr(v, "sku", None) or f"VAR-{v.id}"),
                "price": _to_float(getattr(v, "price", None)),
                "salePrice": _to_float(getattr(v, "sale_price", None)),
                "stock": int(getattr(v, "stock", 0) or 0),
                "manageStock": bool(getattr(v, "manage_stock", True)),
                "allowBackorder": bool(getattr(v, "allow_backorder", False)),
                "canPurchase": _variant_can_purchase(v),
                "status": str(getattr(v, "status", "active") or "active"),
                "isActive": bool(getattr(v, "is_active", True)),
                "imageUrl": getattr(v, "image_url", None),
                "attributeValues": attribute_values,
                "variantName": _build_variant_name(attribute_values, getattr(v, "sku", None)),
                "mediaUrls": media_urls,
                "videoUrls": video_urls,
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

    detail_base = _product_to_item(product, category).model_dump(by_alias=True)
    detail_base["salePrice"] = _to_float(getattr(product, "sale_price", None))

    return PublicProductDetail(
        **detail_base,
        shortDescription=getattr(product, "short_description", None),
        description=getattr(product, "description", None),
        currency=getattr(product, "currency", "VND"),
        brand=getattr(product, "brand", None),
        hasVariants=bool(getattr(product, "has_variants", False)),
        tags=tags,
        specifications=specifications,
        images=images,
        variants=variants,
        variantAttributes=_product_variant_attributes(product, variants),
    )


@router.get("", response_model=ListProductsResponse)
async def list_products(
    response: Response,
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
    include_total: Optional[str] = Query("true", alias="includeTotal"),
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
        if sortBy not in ("createdAt", "price", "name", "bestSelling"):
            raise ValueError("sortBy")
        if order not in ("asc", "desc"):
            raise ValueError("order")
        if status_q not in ("active", "inactive"):
            raise ValueError("status")
        purchasable_only = str(purchasable or "true").strip().lower() not in ("0", "false", "no", "all")
        include_total_bool = str(include_total or "true").strip().lower() not in ("0", "false", "no")

        category_id = _parse_int_id(categoryId, "categoryId")

        filters = []
        if search and search.strip() != "":
            search_filter = _build_product_search_filter(search)
            if search_filter is not None:
                filters.append(search_filter)
        if category_id is not None:
            filters.append(Product.category_id == category_id)
        if min_price_f is not None:
            filters.append(Product.price >= float(min_price_f))
        if max_price_f is not None:
            filters.append(Product.price <= float(max_price_f))

        filters.append(Product.deleted_at.is_(None))
        filters.append(Product.is_active.is_(True))
        filters.append(Product.status == status_q)
        if purchasable_only:
            filters.extend(_sellable_product_filters()[3:])

        sold_count_expr = func.coalesce(func.sum(OrderItem.quantity), 0).label("sold_count")
        sold_count_subquery = (
            select(OrderItem.product_id.label("product_id"), sold_count_expr)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.deleted_at.is_(None),
                Order.status != "cancelled",
            )
            .group_by(OrderItem.product_id)
            .subquery()
        )
        product_sold_count = func.coalesce(sold_count_subquery.c.sold_count, 0).label("sold_count")

        sort_map = {
            "createdAt": Product.created_at,
            "price": Product.price,
            "name": Product.name,
            "bestSelling": product_sold_count,
        }
        sort_col = sort_map[sortBy]
        order_by = sort_col.asc() if order == "asc" else sort_col.desc()

        base_stmt = (
            select(Product, Category, product_sold_count)
            .join(Category, Product.category_id == Category.id)
            .outerjoin(sold_count_subquery, sold_count_subquery.c.product_id == Product.id)
            .options(selectinload(Product.images), selectinload(Product.variants))
        )
        if filters:
            base_stmt = base_stmt.where(*filters)

        offset = (page_i - 1) * limit_i
        fetch_limit = limit_i + 1 if not include_total_bool else limit_i
        stmt = base_stmt.order_by(order_by, Product.created_at.desc()).offset(offset).limit(fetch_limit)

        rows = (await db.execute(stmt)).all()
        has_extra_row = False
        if not include_total_bool and len(rows) > limit_i:
            has_extra_row = True
            rows = rows[:limit_i]

        items = []
        for prod, cat, sold_count in rows:
            setattr(prod, "_sold_count", int(sold_count or 0))
            items.append(_product_to_item(prod, cat))

        if include_total_bool:
            count_stmt = select(func.count()).select_from(Product).join(Category, Product.category_id == Category.id)
            if filters:
                count_stmt = count_stmt.where(*filters)
            total_items = int((await db.execute(count_stmt)).scalar_one())
            total_pages = (total_items + limit_i - 1) // limit_i if total_items > 0 else 0
            has_next = total_pages > 0 and page_i < total_pages
        else:
            total_items = offset + len(items) + (1 if has_extra_row else 0)
            total_pages = page_i + (1 if has_extra_row else 0)
            has_next = has_extra_row
        has_prev = page_i > 1

        apply_public_cache(response)

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
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    product_id = _parse_int_id(id, "id")
    if product_id is None:
        raise HTTPException(status_code=400, detail="id is required")

    stmt = (
        select(Product)
        .options(*_product_detail_load_options())
        .where(Product.id == product_id)
        .limit(1)
    )
    product = (await db.execute(stmt)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    category = await db.get(Category, product.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    sold_count = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.product_id == product.id,
                Order.deleted_at.is_(None),
                Order.status != "cancelled",
            )
        )
    ).scalar_one()
    setattr(product, "_sold_count", int(sold_count or 0))

    detail = _product_to_detail(product, category)
    apply_public_cache(response)
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
        sale_price=_to_float(body.sale_price),
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
            .options(*_product_detail_load_options())
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
    if body.sale_price is not None:
        product.sale_price = _to_float(body.sale_price)
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
            .options(*_product_detail_load_options())
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
