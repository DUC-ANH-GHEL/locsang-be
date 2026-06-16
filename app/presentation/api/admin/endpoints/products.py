from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import Select, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.admin_product import (
    AdminBulkProductsBody,
    AdminProductCreateBody,
    AdminProductQuickPatchBody,
    AdminProductUpdateBody,
    AdminVariantPatchBody,
    BulkUpdateVariantsBody,
    GenerateVariantsBody,
    ProductUploadCleanupBody,
)
from app.core.deps import get_current_user, get_db
from app.domain.models.category import Category
from app.domain.models.product import (
    Product,
    ProductAttribute,
    ProductAttributeValue,
    ProductImage,
    ProductVariant,
    VariantAttributeValue,
)
from app.domain.models.user import User
from app.domain.models.order_item import OrderItem
from app.core.admin_api_error import AdminAPIError


router = APIRouter()


def _normalize_specifications(raw_specs: Optional[Sequence[Any]]) -> List[Dict[str, str]]:
    if not raw_specs:
        return []

    specs: List[Dict[str, str]] = []
    for item in raw_specs:
        label = str(getattr(item, "label", "") or "").strip()
        value = str(getattr(item, "value", "") or "").strip()
        if not label and not value:
            continue
        if not label or not value:
            _admin_error(error_code="SPECIFICATION_INVALID", message="Thông số kỹ thuật cần đủ tên và giá trị")
        specs.append({"label": label[:120], "value": value[:240]})

    if len(specs) > 40:
        _admin_error(error_code="SPECIFICATION_LIMIT", message="Tối đa 40 thông số kỹ thuật cho một sản phẩm")
    return specs


def _parse_bool(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return None


def _status_to_is_active(status_str: Optional[str]) -> Optional[bool]:
    if status_str is None:
        return None
    return status_str == "active"


async def _refresh_product_aggregates(db: AsyncSession, product_id: int) -> None:
    variants = (await db.execute(select(ProductVariant).where(ProductVariant.product_id == product_id))).scalars().all()
    product = await db.get(Product, product_id)
    if not product:
        return

    if variants:
        prices = [v.price for v in variants if v.price is not None]
        if prices:
            product.price = float(min(prices))
        sale_prices = [v.sale_price for v in variants if v.sale_price is not None]
        product.sale_price = float(min(sale_prices)) if sale_prices else None
        product.stock = int(sum([v.stock or 0 for v in variants]))
        product.sku = variants[0].sku
    product.updated_at = datetime.utcnow()


def _stock_status(stock_total: int) -> str:
    if stock_total <= 0:
        return "out"
    if stock_total < 10:
        return "low"
    return "in_stock"


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_media_urls_from_payload(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []

    out: List[str] = []
    seen: set[str] = set()

    def _push(value: Optional[str]) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    _push(payload.get("image_url"))
    _push(payload.get("image"))
    _push(payload.get("thumbnail"))

    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    for item in images:
        if isinstance(item, str):
            _push(item)
        elif isinstance(item, dict):
            _push(item.get("url") or item.get("image_url") or item.get("src"))

    return out


def _is_placeholder_like_image(value: Optional[str]) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return (
        "logo_d2wmlf" in text
        or "/api/placeholder/" in text
        or "placeholder.com" in text
    )


def _resolve_admin_thumbnail(product: Product) -> Optional[str]:
    preferred: List[str] = []
    fallback: List[str] = []
    seen: set[str] = set()

    def _push(value: Optional[str]) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        if _is_placeholder_like_image(text):
            fallback.append(text)
            return
        preferred.append(text)

    # 1) Product images (primary)
    for img in sorted(product.images or [], key=lambda x: (x.sort_order or 0, x.id or 0)):
        if str(getattr(img, "type", "image") or "image").lower() != "image":
            continue
        _push(getattr(img, "url", None))

    # 2) Product thumbnail field
    _push(getattr(product, "thumbnail", None))

    # 3) Variant image fallback
    for variant in sorted(product.variants or [], key=lambda x: x.id or 0):
        _push(getattr(variant, "image_url", None))

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def _build_variant_name(attribute_values: Dict[str, str], fallback_sku: Optional[str]) -> str:
    values = [str(v).strip() for v in (attribute_values or {}).values() if str(v).strip()]
    if values:
        return " / ".join(values)
    return str(fallback_sku or "")


def _parse_sort(sort: Optional[str]) -> Tuple[str, str]:
    # returns (field, direction)
    s = (sort or "created_desc").strip().lower()
    if "_" not in s:
        return ("created", "desc")
    field, direction = s.rsplit("_", 1)
    if direction not in ("asc", "desc"):
        return ("created", "desc")
    return (field, direction)


def _parse_optional_float(raw: Optional[str], field_name: str) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        raise AdminAPIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_QUERY",
            message=f"{field_name} must be a valid number",
        )


@router.get("")
async def admin_list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_q: Optional[str] = Query(None, alias="status"),
    category_id: Optional[int] = None,
    brand: Optional[str] = None,
    has_variants: Optional[str] = None,
    stock_status: Optional[str] = None,
    min_price: Optional[str] = None,
    max_price: Optional[str] = None,
    sort: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    min_price_f = _parse_optional_float(min_price, "min_price")
    max_price_f = _parse_optional_float(max_price, "max_price")

    # Aggregate by variants
    agg = (
        select(
            ProductVariant.product_id.label("product_id"),
            func.count(ProductVariant.id).label("variant_count"),
            func.min(ProductVariant.price).label("price_min"),
            func.max(ProductVariant.price).label("price_max"),
            func.sum(ProductVariant.stock).label("stock_total"),
        )
        .group_by(ProductVariant.product_id)
        .subquery()
    )

    price_min_expr = func.coalesce(
        case((Product.has_variants.is_(True), agg.c.price_min), else_=Product.price),
        Product.price,
    )
    price_max_expr = func.coalesce(
        case((Product.has_variants.is_(True), agg.c.price_max), else_=Product.price),
        Product.price,
    )
    stock_total_expr = func.coalesce(
        case((Product.has_variants.is_(True), agg.c.stock_total), else_=Product.stock),
        Product.stock,
        0,
    )
    variant_count_expr = func.coalesce(agg.c.variant_count, 0)

    filters = [Product.deleted_at.is_(None)]

    if search and search.strip() != "":
        s = search.strip()
        filters.append(
            (Product.name.ilike(f"%{s}%"))
            | (Product.sku.ilike(f"%{s}%"))
            | (Product.slug.ilike(f"%{s}%"))
        )

    if status_q:
        filters.append(Product.status == status_q)

    if category_id is not None:
        filters.append(Product.category_id == category_id)

    if brand and brand.strip() != "":
        filters.append(Product.brand == brand.strip())

    hv = _parse_bool(has_variants)
    if hv is not None:
        filters.append(Product.has_variants.is_(hv))

    if min_price_f is not None:
        filters.append(price_min_expr >= min_price_f)
    if max_price_f is not None:
        filters.append(price_min_expr <= max_price_f)

    if stock_status in ("in_stock", "low", "out"):
        if stock_status == "out":
            filters.append(stock_total_expr <= 0)
        elif stock_status == "low":
            filters.append((stock_total_expr > 0) & (stock_total_expr < 10))
        elif stock_status == "in_stock":
            filters.append(stock_total_expr >= 10)

    field, direction = _parse_sort(sort)
    sort_col = {
        "created": Product.created_at,
        "updated": Product.updated_at,
        "price": price_min_expr,
        "stock": stock_total_expr,
        "name": Product.name,
    }.get(field, Product.created_at)
    order_by = sort_col.asc() if direction == "asc" else sort_col.desc()

    base_stmt = (
        select(
            Product,
            Category,
            price_min_expr.label("price_min"),
            price_max_expr.label("price_max"),
            stock_total_expr.label("stock_total"),
            variant_count_expr.label("variant_count"),
        )
        .options(
            selectinload(Product.images),
            selectinload(Product.variants),
        )
        .outerjoin(agg, agg.c.product_id == Product.id)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(*filters)
    )

    count_stmt = (
        select(func.count(Product.id))
        .select_from(Product)
        .outerjoin(agg, agg.c.product_id == Product.id)
        .where(*filters)
    )

    total = int((await db.execute(count_stmt)).scalar_one())
    offset = (page - 1) * limit

    rows = (
        await db.execute(
            base_stmt.order_by(order_by).offset(offset).limit(limit)
        )
    ).all()

    data: List[Dict[str, Any]] = []
    for product, category, price_min, price_max, stock_total, variant_count in rows:
        stock_total_i = int(stock_total or 0)
        item = {
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "slug": product.slug,
            "thumbnail": _resolve_admin_thumbnail(product),
            "price_min": float(price_min or product.price or 0),
            "price_max": float(price_max or product.price or 0),
            "stock_total": stock_total_i,
            "stock_status": _stock_status(stock_total_i),
            "variant_count": int(variant_count or 0),
            "status": product.status,
            "category_id": product.category_id,
            "category": None if not category else {"id": category.id, "name": category.name},
            "brand": product.brand,
            "has_variants": bool(product.has_variants),
            "created_at": product.created_at,
            "updated_at": product.updated_at,
        }
        data.append(item)

    return {"data": data, "pagination": {"page": page, "limit": limit, "total": total}}


def _admin_error(
    *,
    error_code: str,
    message: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> None:
    raise AdminAPIError(error_code=error_code, message=message, status_code=status_code)


def _raise_duplicate_integrity_error(exc: IntegrityError) -> None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = str(getattr(diag, "constraint_name", "") or "").lower()
    detail = str(getattr(diag, "message_detail", "") or orig or exc).lower()
    signal = f"{constraint} {detail}"
    is_unique_error = any(
        marker in signal
        for marker in ("uniqueviolation", "duplicate key", "unique constraint", "already exists")
    )

    if is_unique_error and "slug" in signal:
        _admin_error(
            error_code="SLUG_DUPLICATE",
            message="Slug đã tồn tại. Vui lòng đổi tên sản phẩm để tạo slug khác.",
            status_code=status.HTTP_409_CONFLICT,
        )

    if is_unique_error and "sku" in signal:
        _admin_error(
            error_code="SKU_DUPLICATE",
            message="SKU đã tồn tại. Vui lòng dùng mã phụ tùng khác.",
            status_code=status.HTTP_409_CONFLICT,
        )

    if any(marker in signal for marker in ("notnullviolation", "not-null constraint", "null value in column")):
        _admin_error(
            error_code="PRODUCT_INVALID",
            message="Thiếu dữ liệu bắt buộc của sản phẩm. Vui lòng kiểm tra lại SKU, giá và tồn kho.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    _admin_error(
        error_code="PRODUCT_DUPLICATE",
        message="Thông tin sản phẩm bị trùng. Vui lòng kiểm tra lại slug và SKU.",
        status_code=status.HTTP_409_CONFLICT,
    )


async def _slug_exists(db: AsyncSession, slug: str, *, exclude_product_id: Optional[int] = None) -> bool:
    stmt = select(func.count(Product.id)).where(Product.slug == slug, Product.deleted_at.is_(None))
    if exclude_product_id is not None:
        stmt = stmt.where(Product.id != exclude_product_id)
    return (await db.scalar(stmt)) > 0


async def _skus_in_use(db: AsyncSession, skus: Sequence[str], *, exclude_variant_ids: Optional[Sequence[int]] = None) -> List[str]:
    if not skus:
        return []
    stmt = (
        select(ProductVariant.sku)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(Product.deleted_at.is_(None), ProductVariant.sku.in_(list(skus)))
    )
    if exclude_variant_ids:
        stmt = stmt.where(~ProductVariant.id.in_(list(exclude_variant_ids)))
    rows = (await db.execute(stmt)).scalars().all()
    return list(set(rows))


async def _product_skus_in_use(
    db: AsyncSession,
    skus: Sequence[str],
    *,
    exclude_product_id: Optional[int] = None,
) -> List[str]:
    if not skus:
        return []
    stmt = select(Product.sku).where(Product.deleted_at.is_(None), Product.sku.in_(list(skus)))
    if exclude_product_id is not None:
        stmt = stmt.where(Product.id != exclude_product_id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(set(rows))


def _released_deleted_value(value: Optional[str], owner_id: int) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return value
    if "__deleted_" in raw:
        return raw
    return f"{raw}__deleted_{owner_id}"


async def _release_deleted_product_unique_fields(db: AsyncSession, product: Product) -> None:
    product.slug = _released_deleted_value(product.slug, product.id) or f"deleted-product-{product.id}"
    product.sku = _released_deleted_value(product.sku, product.id)

    variants = (
        await db.execute(select(ProductVariant).where(ProductVariant.product_id == product.id))
    ).scalars().all()
    for variant in variants:
        variant.sku = _released_deleted_value(variant.sku, variant.id) or f"deleted-variant-{variant.id}"
        variant.status = "inactive"
        variant.is_active = False
        variant.updated_at = datetime.utcnow()


async def _soft_delete_product(db: AsyncSession, product: Product) -> None:
    product.deleted_at = datetime.utcnow()
    product.is_active = False
    product.status = "inactive"
    product.updated_at = datetime.utcnow()
    await _release_deleted_product_unique_fields(db, product)


async def _release_deleted_unique_conflicts(db: AsyncSession, slug: str, skus: Sequence[str]) -> None:
    clean_slug = str(slug or "").strip()
    clean_skus = [str(sku or "").strip() for sku in skus if str(sku or "").strip()]

    product_filters = []
    if clean_slug:
        product_filters.append(Product.slug == clean_slug)
    if clean_skus:
        product_filters.append(Product.sku.in_(clean_skus))

    released_product_ids: set[int] = set()
    if product_filters:
        deleted_products = (
            await db.execute(
                select(Product).where(Product.deleted_at.is_not(None), or_(*product_filters))
            )
        ).scalars().all()
        for product in deleted_products:
            await _release_deleted_product_unique_fields(db, product)
            released_product_ids.add(product.id)

    if clean_skus:
        deleted_variant_products = (
            await db.execute(
                select(Product)
                .join(ProductVariant, ProductVariant.product_id == Product.id)
                .where(Product.deleted_at.is_not(None), ProductVariant.sku.in_(clean_skus))
            )
        ).scalars().unique().all()
        for product in deleted_variant_products:
            if product.id in released_product_ids:
                continue
            await _release_deleted_product_unique_fields(db, product)


def _copy_variant_with_id(variant: Any, variant_id: int) -> Any:
    if hasattr(variant, "model_copy"):
        return variant.model_copy(update={"id": variant_id})
    return variant.copy(update={"id": variant_id})


async def _attach_existing_default_variant(
    db: AsyncSession,
    product_id: int,
    payload: AdminProductUpdateBody,
) -> None:
    if payload.variants is None or len(payload.variants) != 1 or payload.variants[0].id:
        return

    variant_ids = (
        await db.execute(
            select(ProductVariant.id)
            .where(ProductVariant.product_id == product_id)
            .order_by(ProductVariant.id.asc())
            .limit(2)
        )
    ).scalars().all()
    if len(variant_ids) != 1:
        return

    default_variant_id = int(variant_ids[0])
    payload.variants[0] = _copy_variant_with_id(payload.variants[0], default_variant_id)
    if payload.deleted_variant_ids:
        payload.deleted_variant_ids = [vid for vid in payload.deleted_variant_ids if int(vid) != default_variant_id]


def _validate_create_payload(payload: AdminProductCreateBody) -> None:
    if not payload.name:
        _admin_error(error_code="NAME_REQUIRED", message="name is required")

    if payload.has_variants is False:
        if not payload.variants or len(payload.variants) != 1:
            _admin_error(
                error_code="DEFAULT_VARIANT_REQUIRED",
                message="has_variants=false requires exactly 1 default variant",
            )
    else:
        if not payload.variants:
            _admin_error(error_code="VARIANTS_REQUIRED", message="variants is required when has_variants=true")

    seen: set[str] = set()
    for v in payload.variants:
        if not v.sku:
            _admin_error(error_code="SKU_REQUIRED", message="variant.sku is required")
        if v.sku in seen:
            _admin_error(error_code="SKU_DUPLICATE", message="SKU already exists in request")
        seen.add(v.sku)
        if v.price is None or v.price <= 0:
            _admin_error(error_code="PRICE_INVALID", message="variant.price must be > 0")
        if v.sale_price is not None and (v.sale_price <= 0 or v.sale_price > v.price):
            _admin_error(error_code="SALE_PRICE_INVALID", message="Giá sale phải lớn hơn 0 và không vượt giá bán")
        if v.stock is None:
            _admin_error(error_code="STOCK_INVALID", message="Tồn kho là bắt buộc")
        if int(v.stock) < 0 and not bool(v.allow_backorder):
            _admin_error(error_code="STOCK_INVALID", message="Tồn kho âm chỉ hợp lệ khi bật cho phép bán khi hết hàng")


@router.patch("/bulk")
async def admin_bulk_products(
    payload: AdminBulkProductsBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.ids:
        _admin_error(error_code="IDS_REQUIRED", message="ids is required")
    if len(payload.ids) > 500:
        _admin_error(error_code="TOO_MANY_IDS", message="Max 500 product IDs per request")

    updated = 0
    failed: List[Dict[str, Any]] = []

    products = (
        await db.execute(
            select(Product).where(Product.id.in_(payload.ids))
        )
    ).scalars().all()

    by_id = {p.id: p for p in products}
    for product_id in payload.ids:
        product = by_id.get(product_id)
        if not product or product.deleted_at is not None:
            failed.append({"id": product_id, "reason": "NOT_FOUND"})
            continue

        try:
            if payload.action == "status":
                st = payload.data.get("status")
                if st not in ("active", "draft", "inactive", "discontinued"):
                    raise ValueError("status")
                product.status = st
                is_active = _status_to_is_active(st)
                if is_active is not None:
                    product.is_active = is_active
            elif payload.action == "category":
                cid = payload.data.get("category_id")
                if cid is None:
                    raise ValueError("category_id")
                product.category_id = int(cid)
            elif payload.action == "delete":
                await _soft_delete_product(db, product)
            else:
                raise ValueError("action")

            if payload.action != "delete":
                product.updated_at = datetime.utcnow()
            updated += 1
        except Exception:
            failed.append({"id": product_id, "reason": "INVALID_DATA"})

    await db.commit()

    return {"success": True, "updated": updated, "failed": failed}


@router.patch("/variants/{variant_id}")
async def admin_patch_variant(
    variant_id: int,
    payload: AdminVariantPatchBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variant = await db.get(ProductVariant, variant_id)
    if not variant:
        _admin_error(error_code="VARIANT_NOT_FOUND", message="Variant not found", status_code=404)

    if payload.price is not None and payload.price <= 0:
        _admin_error(error_code="PRICE_INVALID", message="price must be > 0")
    if payload.stock is not None and payload.stock < 0:
        _admin_error(error_code="STOCK_INVALID", message="stock must be >= 0")

    if payload.price is not None:
        variant.price = float(payload.price)
    if payload.stock is not None:
        variant.stock = int(payload.stock)
    if payload.status is not None:
        variant.status = payload.status
        variant.is_active = (payload.status == "active")

    variant.updated_at = datetime.utcnow()
    await _refresh_product_aggregates(db, variant.product_id)
    await db.commit()

    return {"success": True}


@router.patch("/{product_id}")
async def admin_quick_patch_product(
    product_id: int,
    payload: AdminProductQuickPatchBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await _get_product_or_404(db, product_id)

    if payload.price is not None and payload.price <= 0:
        _admin_error(error_code="PRICE_INVALID", message="price must be > 0")
    if payload.stock is not None and payload.stock < 0:
        _admin_error(error_code="STOCK_INVALID", message="stock must be >= 0")

    if payload.status is not None:
        product.status = payload.status
        product.is_active = (payload.status == "active")
    if payload.category_id is not None:
        product.category_id = int(payload.category_id)

    # If product has variants, price/stock live on variants; still allow override compat fields.
    if payload.price is not None:
        product.price = float(payload.price)
    if payload.stock is not None:
        product.stock = int(payload.stock)

    product.updated_at = datetime.utcnow()
    await db.commit()

    return {"success": True}


async def _get_product_or_404(db: AsyncSession, product_id: int) -> Product:
    stmt: Select[tuple[Product]] = (
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.images),
            selectinload(Product.variants)
            .selectinload(ProductVariant.attribute_values)
            .selectinload(VariantAttributeValue.attribute_value),
            selectinload(Product.variants)
            .selectinload(ProductVariant.attribute_values)
            .selectinload(VariantAttributeValue.attribute),
            selectinload(Product.attributes).selectinload(ProductAttribute.values),
        )
    )
    product = (await db.execute(stmt)).scalars().first()
    if not product or product.deleted_at is not None:
        raise AdminAPIError(error_code="NOT_FOUND", message="Product not found", status_code=404)
    return product


async def _load_attribute_value_lookup(db: AsyncSession, product_id: int) -> tuple[Dict[str, ProductAttribute], Dict[tuple[str, str], int]]:
    stmt = (
        select(ProductAttribute)
        .where(ProductAttribute.product_id == product_id)
        .options(selectinload(ProductAttribute.values))
    )
    attrs = (await db.execute(stmt)).scalars().all()
    attribute_by_name: Dict[str, ProductAttribute] = {}
    value_id_by_pair: Dict[tuple[str, str], int] = {}
    for a in attrs:
        attribute_by_name[a.name] = a
        for v in a.values:
            value_id_by_pair[(a.name, v.value)] = v.id
    return attribute_by_name, value_id_by_pair


def _product_detail_response(product: Product, category: Optional[Category] = None) -> Dict[str, Any]:
    media = [
        {"url": m.url, "type": getattr(m, "type", "image"), "sort_order": m.sort_order, "public_id": m.public_id}
        for m in sorted(product.images, key=lambda x: x.sort_order)
    ]

    attributes = []
    for a in product.attributes:
        attributes.append(
            {
                "id": a.id,
                "name": a.name,
                "values": [v.value for v in sorted(a.values, key=lambda x: x.id)],
            }
        )

    variants = []
    for v in product.variants:
        attr_map: Dict[str, str] = {}
        for av in v.attribute_values:
            if av.attribute and av.attribute_value:
                attr_map[av.attribute.name] = av.attribute_value.value
        variants.append(
            {
                "id": v.id,
                "sku": v.sku,
                "price": v.price,
                "sale_price": v.sale_price,
                "stock": v.stock,
                "manage_stock": v.manage_stock,
                "allow_backorder": v.allow_backorder,
                "status": v.status,
                "attribute_values": attr_map,
                "variant_name": _build_variant_name(attr_map, v.sku),
                "image_url": v.image_url,
            }
        )

    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "slug": product.slug,
        "short_description": product.short_description,
        "description": product.description,
        "price": product.price,
        "sale_price": product.sale_price,
        "currency": product.currency,
        "stock": product.stock,
        "thumbnail": product.thumbnail,
        "status": product.status,
        "is_active": product.is_active,
        "category_id": product.category_id,
        "category_name": category.name if category else None,
        "category": {"id": category.id, "name": category.name} if category else None,
        "brand": product.brand,
        "tags": product.tags or [],
        "specifications": product.specifications or [],
        "has_variants": product.has_variants,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "media": media,
        "attributes": attributes,
        "variants": variants,
    }


@router.post("/upload-image")
async def admin_upload_product_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File tải lên phải là ảnh.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File ảnh rỗng.")

    max_size = 10 * 1024 * 1024
    if len(data) > max_size:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ảnh vượt quá 10MB. Vui lòng chọn ảnh nhỏ hơn.")

    try:
        result = cloudinary.uploader.upload(
            data,
            folder="products",
            resource_type="image",
            format="webp",
            overwrite=False,
            use_filename=True,
        )
        secure_url = (result or {}).get("secure_url")
        public_id = (result or {}).get("public_id")
        if not secure_url:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upload ảnh thất bại, không nhận được URL.")
        return {"success": True, "url": secure_url, "public_id": public_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Upload ảnh thất bại: {exc}") from exc


@router.post("/upload-image/cleanup")
async def admin_cleanup_uploaded_product_images(
    payload: ProductUploadCleanupBody,
    current_user: User = Depends(get_current_user),
):
    cleaned = 0
    failed: List[str] = []
    allowed_prefix = "products/"

    for raw_public_id in payload.public_ids:
        public_id = str(raw_public_id or "").strip()
        if not public_id or not public_id.startswith(allowed_prefix):
            continue
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
            if (result or {}).get("result") in ("ok", "not found"):
                cleaned += 1
            else:
                failed.append(public_id)
        except Exception:
            failed.append(public_id)

    return {"success": len(failed) == 0, "cleaned": cleaned, "failed": failed}


@router.post("", status_code=status.HTTP_201_CREATED)
async def admin_create_product(
    payload: AdminProductCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _validate_create_payload(payload)

        skus = [v.sku for v in payload.variants]
        await _release_deleted_unique_conflicts(db, payload.slug, skus)

        if await _slug_exists(db, payload.slug):
            _admin_error(error_code="SLUG_DUPLICATE", message="Slug already exists", status_code=status.HTTP_409_CONFLICT)

        existing_product_skus = await _product_skus_in_use(db, skus)
        if existing_product_skus:
            _admin_error(
                error_code="SKU_DUPLICATE",
                message=f"SKU already exists: {existing_product_skus[0]}",
                status_code=status.HTTP_409_CONFLICT,
            )
        existing = await _skus_in_use(db, skus)
        if existing:
            _admin_error(error_code="SKU_DUPLICATE", message=f"SKU already exists: {existing[0]}", status_code=status.HTTP_409_CONFLICT)

        product = Product(
            name=payload.name,
            slug=payload.slug,
            short_description=payload.short_description,
            description=payload.description,
            status=payload.status,
            category_id=payload.category_id,
            brand=payload.brand,
            tags=payload.tags,
            specifications=_normalize_specifications(payload.specifications),
            has_variants=payload.has_variants,
            is_active=(payload.status == "active"),
        )

        product.price = min([v.price for v in payload.variants])
        sale_prices = [v.sale_price for v in payload.variants if v.sale_price is not None]
        product.sale_price = min(sale_prices) if sale_prices else None
        product.sku = payload.variants[0].sku
        product.stock = sum([v.stock for v in payload.variants])

        db.add(product)
        await db.flush()

        # Media
        for m in payload.media:
            db.add(
                ProductImage(
                    product_id=product.id,
                    url=m.url,
                    type=m.type,
                    public_id=m.public_id,
                    sort_order=m.sort_order,
                    is_primary=(m.sort_order == 1),
                )
            )

        # Attributes + values
        attribute_by_name: Dict[str, ProductAttribute] = {}
        value_id_by_pair: Dict[tuple[str, str], int] = {}

        for attr in payload.attributes:
            a = ProductAttribute(product_id=product.id, name=attr.name)
            db.add(a)
            await db.flush()
            attribute_by_name[attr.name] = a

            for val in attr.values:
                av = ProductAttributeValue(attribute_id=a.id, value=val)
                db.add(av)
                await db.flush()
                value_id_by_pair[(attr.name, val)] = av.id

        # Variants + variant_attribute_values
        for v in payload.variants:
            variant = ProductVariant(
                product_id=product.id,
                sku=v.sku,
                price=v.price,
                sale_price=v.sale_price,
                stock=v.stock,
                manage_stock=v.manage_stock,
                allow_backorder=v.allow_backorder,
                status=v.status,
                is_active=(v.status == "active"),
                image_url=v.image_url,
            )
            db.add(variant)
            await db.flush()

            for attr_name, chosen in (v.attribute_values or {}).items():
                if attr_name not in attribute_by_name:
                    _admin_error(error_code="ATTRIBUTE_INVALID", message=f"Unknown attribute: {attr_name}")
                if (attr_name, chosen) not in value_id_by_pair:
                    _admin_error(error_code="ATTRIBUTE_VALUE_INVALID", message=f"Invalid value for {attr_name}: {chosen}")

                attribute = attribute_by_name[attr_name]
                attribute_value_id = value_id_by_pair[(attr_name, chosen)]
                db.add(
                    VariantAttributeValue(
                        variant_id=variant.id,
                        attribute_id=attribute.id,
                        attribute_value_id=attribute_value_id,
                    )
                )

        await db.commit()

        return {
            "success": True,
            "message": "Product created successfully",
            "data": {"id": product.id, "slug": product.slug},
        }
    except HTTPException:
        raise
    except AdminAPIError:
        raise
    except IntegrityError as exc:
        await db.rollback()
        _raise_duplicate_integrity_error(exc)
    except Exception as e:
        _admin_error(error_code="INTERNAL_ERROR", message=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/{product_id}")
async def admin_update_product(
    product_id: int,
    payload: AdminProductUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        product = await _get_product_or_404(db, product_id)

        incoming_skus_for_release = [v.sku for v in payload.variants] if payload.variants is not None else []
        await _release_deleted_unique_conflicts(db, payload.slug or "", incoming_skus_for_release)

        if payload.slug and await _slug_exists(db, payload.slug, exclude_product_id=product_id):
            _admin_error(error_code="SLUG_DUPLICATE", message="Slug already exists", status_code=status.HTTP_409_CONFLICT)

        # Update product
        for field in [
            "name",
            "slug",
            "short_description",
            "description",
            "status",
            "category_id",
            "brand",
            "has_variants",
        ]:
            val = getattr(payload, field)
            if val is not None:
                setattr(product, field, val)

        if payload.tags is not None:
            product.tags = payload.tags

        if payload.specifications is not None:
            product.specifications = _normalize_specifications(payload.specifications)

        if payload.status is not None:
            product.is_active = (payload.status == "active")

        if payload.variants is not None:
            await _attach_existing_default_variant(db, product.id, payload)

        # Sync media (replace)
        if payload.media is not None:
            await db.execute(delete(ProductImage).where(ProductImage.product_id == product.id))
            for m in payload.media:
                db.add(
                    ProductImage(
                        product_id=product.id,
                        url=m.url,
                        type=m.type,
                        public_id=m.public_id,
                        sort_order=m.sort_order,
                        is_primary=(m.sort_order == 1),
                    )
                )

        # Delete attributes explicitly
        if payload.deleted_attribute_ids:
            await db.execute(
                delete(ProductAttribute).where(
                    ProductAttribute.product_id == product.id,
                    ProductAttribute.id.in_(payload.deleted_attribute_ids),
                )
            )

        # Sync attributes (upsert-ish)
        attribute_by_name: Dict[str, ProductAttribute] = {}
        value_id_by_pair: Dict[tuple[str, str], int] = {}

        if payload.attributes is not None:
            for attr in payload.attributes:
                if attr.id:
                    a = (await db.execute(
                        select(ProductAttribute).where(
                            ProductAttribute.product_id == product.id,
                            ProductAttribute.id == attr.id,
                        )
                    )).scalars().first()
                    if not a:
                        _admin_error(error_code="ATTRIBUTE_NOT_FOUND", message=f"Attribute not found: {attr.id}")
                    a.name = attr.name
                else:
                    a = ProductAttribute(product_id=product.id, name=attr.name)
                    db.add(a)
                    await db.flush()

                attribute_by_name[attr.name] = a

                # Replace values for this attribute
                await db.execute(delete(ProductAttributeValue).where(ProductAttributeValue.attribute_id == a.id))
                for val in attr.values:
                    av = ProductAttributeValue(attribute_id=a.id, value=val)
                    db.add(av)
                    await db.flush()
                    value_id_by_pair[(attr.name, val)] = av.id
        else:
            attribute_by_name, value_id_by_pair = await _load_attribute_value_lookup(db, product.id)

        # Delete variants explicitly
        if payload.deleted_variant_ids:
            # Block deletion when referenced by order_items
            used_count = await db.scalar(
                select(func.count(OrderItem.id)).where(OrderItem.product_variant_id.in_(payload.deleted_variant_ids))
            )
            if used_count and used_count > 0:
                _admin_error(
                    error_code="VARIANT_HAS_ORDERS",
                    message="Cannot delete variant that has order items",
                    status_code=status.HTTP_409_CONFLICT,
                )
            await db.execute(
                delete(ProductVariant).where(
                    ProductVariant.product_id == product.id,
                    ProductVariant.id.in_(payload.deleted_variant_ids),
                )
            )

        # Sync variants
        if payload.variants is not None:
            # Validate sku uniqueness (in request)
            seen: set[str] = set()
            for v in payload.variants:
                if v.sku in seen:
                    _admin_error(error_code="SKU_DUPLICATE", message="SKU already exists in request")
                seen.add(v.sku)
                if v.price is None or v.price <= 0:
                    _admin_error(error_code="PRICE_INVALID", message="variant.price must be > 0")
                if v.sale_price is not None and (v.sale_price <= 0 or v.sale_price > v.price):
                    _admin_error(error_code="SALE_PRICE_INVALID", message="Giá sale phải lớn hơn 0 và không vượt giá bán")
                if v.stock is None:
                    _admin_error(error_code="STOCK_INVALID", message="Tồn kho là bắt buộc")
                if int(v.stock) < 0 and not bool(v.allow_backorder):
                    _admin_error(error_code="STOCK_INVALID", message="Tồn kho âm chỉ hợp lệ khi bật cho phép bán khi hết hàng")

            incoming_skus = [v.sku for v in payload.variants]
            exclude_ids = [v.id for v in payload.variants if v.id]
            existing_product_skus = await _product_skus_in_use(db, incoming_skus, exclude_product_id=product.id)
            if existing_product_skus:
                _admin_error(
                    error_code="SKU_DUPLICATE",
                    message=f"SKU already exists: {existing_product_skus[0]}",
                    status_code=status.HTTP_409_CONFLICT,
                )
            existing = await _skus_in_use(db, incoming_skus, exclude_variant_ids=exclude_ids)
            if existing:
                _admin_error(error_code="SKU_DUPLICATE", message=f"SKU already exists: {existing[0]}", status_code=status.HTTP_409_CONFLICT)

            for v in payload.variants:
                if v.id:
                    variant = (await db.execute(
                        select(ProductVariant).where(ProductVariant.product_id == product.id, ProductVariant.id == v.id)
                    )).scalars().first()
                    if not variant:
                        _admin_error(error_code="VARIANT_NOT_FOUND", message=f"Variant not found: {v.id}")
                else:
                    variant = ProductVariant(product_id=product.id)
                    db.add(variant)

                variant.sku = v.sku
                variant.price = v.price
                variant.sale_price = v.sale_price
                variant.stock = v.stock
                variant.manage_stock = v.manage_stock
                variant.allow_backorder = v.allow_backorder
                variant.status = v.status
                variant.is_active = (v.status == "active")
                variant.image_url = v.image_url
                await db.flush()

                # Replace mappings
                await db.execute(delete(VariantAttributeValue).where(VariantAttributeValue.variant_id == variant.id))
                for attr_name, chosen in (v.attribute_values or {}).items():
                    if (attr_name, chosen) not in value_id_by_pair:
                        _admin_error(error_code="ATTRIBUTE_VALUE_INVALID", message=f"Invalid value for {attr_name}: {chosen}")
                    attribute_value_id = value_id_by_pair[(attr_name, chosen)]
                    attribute_id = attribute_by_name[attr_name].id
                    db.add(
                        VariantAttributeValue(
                            variant_id=variant.id,
                            attribute_id=attribute_id,
                            attribute_value_id=attribute_value_id,
                        )
                    )

            # Update back-compat aggregate fields
            refreshed_variants = (await db.execute(
                select(ProductVariant).where(ProductVariant.product_id == product.id)
            )).scalars().all()
            if refreshed_variants:
                product.price = min([rv.price or 0 for rv in refreshed_variants])
                sale_prices = [rv.sale_price for rv in refreshed_variants if rv.sale_price is not None]
                product.sale_price = min(sale_prices) if sale_prices else None
                product.sku = refreshed_variants[0].sku
                product.stock = sum([rv.stock for rv in refreshed_variants])

        product.updated_at = datetime.utcnow()
        await db.commit()

        return {"success": True, "message": "Product updated successfully"}
    except HTTPException:
        await db.rollback()
        raise
    except AdminAPIError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        _raise_duplicate_integrity_error(exc)
    except Exception as e:
        await db.rollback()
        _admin_error(error_code="INTERNAL_ERROR", message=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{product_id}")
async def admin_get_product_detail(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await _get_product_or_404(db, product_id)
    category = None
    if product.category_id:
        category = await db.get(Category, product.category_id)
    return _product_detail_response(product, category)


@router.delete("/{product_id}")
async def admin_soft_delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await _get_product_or_404(db, product_id)
    await _soft_delete_product(db, product)
    await db.commit()
    return {"success": True, "message": "Product deleted successfully"}


@router.patch("/{product_id}/variants/bulk")
async def admin_bulk_update_variants(
    product_id: int,
    payload: BulkUpdateVariantsBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.variant_ids:
        _admin_error(error_code="VARIANT_IDS_REQUIRED", message="variant_ids is required")
    if len(payload.variant_ids) > 200:
        _admin_error(error_code="TOO_MANY_IDS", message="Max 200 variant IDs per request")

    allowed_fields = {
        "price",
        "sale_price",
        "stock",
        "status",
        "manage_stock",
        "allow_backorder",
        "image_url",
    }
    update_data = {k: v for k, v in (payload.update or {}).items() if k in allowed_fields}
    if not update_data:
        _admin_error(error_code="UPDATE_INVALID", message="No valid fields to update")

    stmt = (
        update(ProductVariant)
        .where(ProductVariant.product_id == product_id, ProductVariant.id.in_(payload.variant_ids))
        .values(**update_data)
    )
    result = await db.execute(stmt)
    await db.commit()

    return {"success": True, "message": "Variants updated successfully", "data": {"updated": result.rowcount}}


@router.post("/generate-variants")
async def admin_generate_variants(
    payload: GenerateVariantsBody,
    current_user: User = Depends(get_current_user),
):
    attrs = [a for a in payload.attributes if a.name and a.values]
    if not attrs:
        return {"variants": []}

    names = [a.name for a in attrs]
    values_lists = [a.values for a in attrs]

    variants = []
    for combo in itertools.product(*values_lists):
        attribute_values = {names[i]: combo[i] for i in range(len(names))}
        variants.append({"attribute_values": attribute_values})

    return {"variants": variants}
