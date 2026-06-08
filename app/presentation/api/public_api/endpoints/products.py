from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.public_product import (
    CreateProductReviewBody,
    CreateProductBody,
    ListProductsResponse,
    ProductDetailResponse,
    ProductComboOffer,
    ProductComboItem,
    ProductPromotionOffer,
    ProductPromotionItem,
    ProductReviewItem,
    ProductReviewsResponse,
    ProductReviewSummary,
    PublicProductDetail,
    PublicProductItem,
    UpdateProductBody,
)
from app.core.config import settings
from app.core.deps import get_db
from app.domain.models.category import Category
from app.domain.models.order import Order, OrderStatus
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductImage
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
        media_urls, _video_urls = _extract_variant_media(getattr(variant, "pancake_payload", None), getattr(variant, "image_url", None))
        for media_url in media_urls:
            _push(media_url)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def _to_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _first_present_dict(*values: Any) -> Optional[dict]:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _iter_dicts(value: Any) -> Iterable[dict]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _collect_combo_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("combo_products", "combo_items", "combo_variations", "gift_products"):
        candidates.extend(list(_iter_dicts(payload.get(key))))
    return candidates


def _extract_combo_pancake_product_id(item: dict[str, Any]) -> Optional[str]:
    nested = _first_present_dict(item.get("product"), item.get("item"), item.get("variation"))
    for source in (item, nested):
        if not isinstance(source, dict):
            continue
        raw = _to_text(
            source.get("pancake_product_id")
            or source.get("product_id")
            or source.get("productId")
            or source.get("id")
        )
        if raw:
            return raw
    return None


def _collect_promotion_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_iter_dicts(payload.get("promotions")))


def _infer_promotion_kind(promotion_type: Optional[str], promotion: dict[str, Any]) -> str:
    token = str(promotion_type or "").strip().lower()
    if not token:
        token = str(
            promotion.get("program_type")
            or promotion.get("action_type")
            or promotion.get("discount_type")
            or promotion.get("type")
            or ""
        ).strip().lower()

    if token == "discount_by_attachment_products" or any(key in token for key in ("attach", "attachment", "bonus", "free", "gift")):
        return "discount_by_attachment_products"
    if token in {"discount_by_order_price", "order_price", "order_value"}:
        return "order_value_discount"
    if token in {"discount_by_coupon_id", "coupon", "promo_code"}:
        return "voucher_coupon"
    if token in {"fixed_prices", "fixed_price"}:
        return "fixed_prices"
    if "combo" in token:
        return "combo_bundle"
    if any(key in token for key in ("product", "item", "goods", "variation")):
        return "discount_by_product"
    return "general"


def _collect_promotion_items(promotion: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in (
        "items",
        "products",
        "applied_products",
        "variations",
        "bonus_items",
        "bonus_products",
        "free_products",
        "gift_products",
        "combo_products",
        "combo_items",
    ):
        items.extend(list(_iter_dicts(promotion.get(key))))
    return items


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        if isinstance(value, list) and len(value) == 0:
            continue
        if isinstance(value, dict):
            nested = _compact_dict(value)
            if nested:
                compact[key] = nested
            continue
        compact[key] = value
    return compact


def _build_promotion_gifts(promotion: dict[str, Any]) -> list[dict[str, Any]]:
    gifts: list[dict[str, Any]] = []
    for raw in _collect_promotion_items(promotion):
        if not isinstance(raw, dict):
            continue
        nested = _first_present_dict(raw.get("product"), raw.get("item"), raw.get("variation")) or {}
        label = (
            _to_text(raw.get("name"))
            or _to_text(raw.get("title"))
            or _to_text(raw.get("product_name"))
            or _to_text(nested.get("name"))
            or _to_text(nested.get("title"))
        )
        if not label:
            continue
        quantity = _to_int(
            raw.get("quantity")
            or raw.get("qty")
            or raw.get("amount")
            or nested.get("quantity")
            or nested.get("qty")
            or 1,
            1,
        ) or 1
        gifts.append(
            _compact_dict(
                {
                    "label": label,
                    "quantity": max(1, quantity),
                    "image": _to_text(raw.get("image") or raw.get("image_url") or nested.get("image") or nested.get("image_url")),
                    "pancake_product_id": _extract_combo_pancake_product_id(raw),
                }
            )
        )
    return gifts


def _build_promotion_meta(promotion: dict[str, Any], promotion_type: Optional[str], promotion_kind: str) -> dict[str, Any]:
    coupon_info = promotion.get("coupon_info") if isinstance(promotion.get("coupon_info"), dict) else {}
    promo_code_info = promotion.get("promo_code_info") if isinstance(promotion.get("promo_code_info"), dict) else {}

    discount_value = _extract_first_positive_number(
        coupon_info.get("discount"),
        promo_code_info.get("discount"),
        promotion.get("discount"),
        promotion.get("discount_money"),
        promotion.get("discount_amount"),
    )
    is_percent = bool(coupon_info.get("is_percent") or promo_code_info.get("is_percent"))
    max_discount = _extract_first_positive_number(
        coupon_info.get("max_discount_by_percent"),
        promo_code_info.get("max_discount_by_percent"),
    )

    level_info = promotion.get("level_info") if isinstance(promotion.get("level_info"), list) else []
    if level_info:
        first_level = next((lv for lv in level_info if isinstance(lv, dict)), None)
        if first_level:
            discount_value = discount_value or _extract_first_positive_number(first_level.get("discount"))
            is_percent = is_percent or bool(first_level.get("is_percent"))

    tiers: list[dict[str, Any]] = []
    for level in level_info:
        if not isinstance(level, dict):
            continue
        tiers.append(
            _compact_dict(
                {
                    "from_quantity": _to_int(level.get("from_quantity")),
                    "to_quantity": _to_int(level.get("to_quantity")),
                    "discount": _extract_first_positive_number(level.get("discount")),
                    "is_percent": bool(level.get("is_percent")),
                    "max_discount_by_percent": _extract_first_positive_number(level.get("max_discount_by_percent")),
                }
            )
        )

    order_tiers_raw = promotion.get("arr_level_promotion") if isinstance(promotion.get("arr_level_promotion"), list) else []
    order_tiers: list[dict[str, Any]] = []
    for level in order_tiers_raw:
        if not isinstance(level, dict):
            continue
        order_tiers.append(
            _compact_dict(
                {
                    "from_total": _extract_first_positive_number(level.get("from_total"), level.get("from_price"), level.get("start_price")),
                    "to_total": _extract_first_positive_number(level.get("to_total"), level.get("to_price"), level.get("end_price")),
                    "discount": _extract_first_positive_number(level.get("discount"), level.get("discount_money"), level.get("discount_amount")),
                    "is_percent": bool(level.get("is_percent")),
                }
            )
        )

    fixed_price = _extract_first_positive_number(promotion.get("fixed_prices"))

    scope = "product"
    promo_type_token = str(promotion_type or "").strip().lower()
    if promotion_kind in {"order_value_discount", "voucher_coupon"} or promo_type_token in {"discount_by_order_price", "discount_by_coupon_id", "coupon"}:
        scope = "order"

    return _compact_dict(
        {
            "scope": scope,
            "voucher_code": _to_text(coupon_info.get("coupon_code") or promo_code_info.get("code") or promotion.get("code")),
            "discount_value": discount_value,
            "is_percent": is_percent,
            "max_discount": max_discount,
            "fixed_price": fixed_price,
            "minimum_order_total": _extract_first_positive_number(
                coupon_info.get("order_from"),
                promo_code_info.get("order_from"),
                promotion.get("order_from"),
                promotion.get("minimum_order_price"),
            ),
            "minimum_quantity": _to_int(promotion.get("minimum_quantity") or promotion.get("discount_by_quantity") or promotion.get("product_quantity")),
            "tiers": tiers[:8],
            "order_tiers": order_tiers[:8],
            "gifts": _build_promotion_gifts(promotion)[:8],
        }
    )


def _extract_first_positive_number(*values: Any) -> Optional[float]:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None and numeric > 0:
            return float(numeric)
    return None


def _estimate_discounted_price(
    *,
    base_price: Optional[float],
    promotion: dict[str, Any],
    item: dict[str, Any],
    nested: dict[str, Any],
) -> Optional[float]:
    base = _to_float(base_price)
    if base is None or base <= 0:
        return None

    direct_price = _extract_first_positive_number(
        item.get("discounted_price"),
        item.get("price_after_discount"),
        item.get("discount_price"),
        nested.get("discounted_price"),
        nested.get("price_after_discount"),
        nested.get("discount_price"),
        promotion.get("discounted_price"),
        promotion.get("price_after_discount"),
        promotion.get("discount_price"),
    )
    if direct_price is not None and direct_price < base:
        return round(direct_price, 2)

    fixed_price = _extract_first_positive_number(
        item.get("fixed_prices"),
        nested.get("fixed_prices"),
        promotion.get("fixed_prices"),
    )
    if fixed_price is not None and fixed_price < base:
        return round(float(fixed_price), 2)

    coupon_item_info = item.get("coupon_item_info") if isinstance(item.get("coupon_item_info"), dict) else {}
    coupon_info = promotion.get("coupon_info") if isinstance(promotion.get("coupon_info"), dict) else {}
    promo_code_info = promotion.get("promo_code_info") if isinstance(promotion.get("promo_code_info"), dict) else {}

    item_discount = _extract_first_positive_number(coupon_item_info.get("discount"), coupon_item_info.get("value"))
    item_is_percent = bool(coupon_item_info.get("is_percent")) if coupon_item_info else False
    item_max_pct_amount = _extract_first_positive_number(coupon_item_info.get("max_discount_by_percent"))
    if item_discount is not None:
        if item_is_percent:
            pct = max(0.0, min(100.0, float(item_discount)))
            amount = base * (pct / 100.0)
            if item_max_pct_amount is not None and amount > item_max_pct_amount:
                amount = float(item_max_pct_amount)
            estimated = max(0.0, base - amount)
            if estimated < base:
                return round(estimated, 2)
        else:
            estimated = max(0.0, base - float(item_discount))
            if estimated < base:
                return round(estimated, 2)

    # discount_by_product often defines quantity tiers in level_info
    level_info = item.get("level_info") if isinstance(item.get("level_info"), list) else []
    quantity = _to_int(item.get("quantity"), 1) or 1
    selected_level: Optional[dict[str, Any]] = None
    for level in level_info:
        if not isinstance(level, dict):
            continue
        from_qty = _to_int(level.get("from_quantity"), 1) or 1
        to_qty = _to_int(level.get("to_quantity"), from_qty) or from_qty
        if from_qty <= quantity <= to_qty:
            selected_level = level
            break
    if selected_level is None and level_info:
        selected_level = next((lv for lv in level_info if isinstance(lv, dict)), None)

    if selected_level is not None:
        lv_discount = _extract_first_positive_number(selected_level.get("discount"))
        lv_is_percent = bool(selected_level.get("is_percent"))
        if lv_discount is not None:
            if lv_is_percent:
                pct = max(0.0, min(100.0, float(lv_discount)))
                estimated = base * (1.0 - (pct / 100.0))
                if estimated < base:
                    return round(estimated, 2)
            else:
                estimated = max(0.0, base - float(lv_discount))
                if estimated < base:
                    return round(estimated, 2)

    # coupon / discount_by_coupon_id from promotion-level config
    promo_discount = _extract_first_positive_number(
        coupon_info.get("discount"),
        promo_code_info.get("discount"),
    )
    promo_is_percent = bool(coupon_info.get("is_percent") or promo_code_info.get("is_percent"))
    promo_max_pct_amount = _extract_first_positive_number(
        coupon_info.get("max_discount_by_percent"),
        promo_code_info.get("max_discount_by_percent"),
    )
    if promo_discount is not None:
        if promo_is_percent:
            pct = max(0.0, min(100.0, float(promo_discount)))
            amount = base * (pct / 100.0)
            if promo_max_pct_amount is not None and amount > promo_max_pct_amount:
                amount = float(promo_max_pct_amount)
            estimated = max(0.0, base - amount)
            if estimated < base:
                return round(estimated, 2)
        else:
            estimated = max(0.0, base - float(promo_discount))
            if estimated < base:
                return round(estimated, 2)

    discount_amount = _extract_first_positive_number(
        item.get("discount_money"),
        item.get("discount_amount"),
        item.get("amount_discount"),
        nested.get("discount_money"),
        nested.get("discount_amount"),
        nested.get("amount_discount"),
        promotion.get("discount_money"),
        promotion.get("discount_amount"),
        promotion.get("amount_discount"),
        promotion.get("discount_value") if str(promotion.get("discount_type") or "").lower() in {"money", "amount", "fixed", "vnd"} else None,
    )
    if discount_amount is not None and discount_amount > 0:
        estimated = max(0.0, base - float(discount_amount))
        if estimated < base:
            return round(estimated, 2)

    discount_percent = _extract_first_positive_number(
        item.get("discount_percent"),
        item.get("discount_percentage"),
        item.get("percent"),
        nested.get("discount_percent"),
        nested.get("discount_percentage"),
        nested.get("percent"),
        promotion.get("discount_percent"),
        promotion.get("discount_percentage"),
        promotion.get("percent"),
        promotion.get("discount_value") if str(promotion.get("discount_type") or "").lower() in {"percent", "%", "percentage"} else None,
    )
    if discount_percent is not None and discount_percent > 0:
        pct = max(0.0, min(100.0, float(discount_percent)))
        estimated = base * (1.0 - (pct / 100.0))
        if estimated < base:
            return round(estimated, 2)

    # Coupon-like promotions often encode value with a unit field.
    coupon_value = _extract_first_positive_number(promotion.get("value"), promotion.get("coupon_value"))
    coupon_unit = str(
        promotion.get("value_type")
        or promotion.get("coupon_type")
        or promotion.get("unit")
        or promotion.get("type_value")
        or ""
    ).strip().lower()
    if coupon_value is not None and coupon_unit:
        if coupon_unit in {"percent", "%", "percentage"}:
            pct = max(0.0, min(100.0, float(coupon_value)))
            estimated = base * (1.0 - (pct / 100.0))
            if estimated < base:
                return round(estimated, 2)
        if coupon_unit in {"money", "amount", "fixed", "vnd"}:
            estimated = max(0.0, base - float(coupon_value))
            if estimated < base:
                return round(estimated, 2)

    return None


async def _resolve_active_discounted_prices(product: Product) -> dict[str, float]:
    """Resolve discounted prices by promotion id via Pancake active-promotion API.

    This is a fallback for tenants where `promotion_advance` payload does not
    include item-level discounted prices.
    """
    base_url = (settings.PANCAKE_BASE_URL or "").rstrip("/")
    api_key = settings.PANCAKE_API_KEY
    shop_id = settings.PANCAKE_SHOP_ID
    if not (base_url and api_key and shop_id):
        return {}
    shop_id_num = _to_int(shop_id)
    if shop_id_num is None:
        return {}

    pancake_product_id = _to_text(getattr(product, "pancake_product_id", None))
    if not pancake_product_id:
        return {}

    variants = [v for v in (product.variants or []) if getattr(v, "is_active", True)]
    primary_variant = variants[0] if variants else None
    pancake_variation_id = _to_text(getattr(primary_variant, "pancake_variation_id", None))
    if not pancake_variation_id:
        return {}

    base_price = _to_float(getattr(primary_variant, "sale_price", None)) or _to_float(getattr(primary_variant, "price", None))
    if base_price is None:
        base_price = _to_float(getattr(product, "sale_price", None)) or _to_float(getattr(product, "price", None)) or 0.0

    payload = {
        "order": {
            "shop_id": int(shop_id_num),
            "items": [
                {
                    "product_id": pancake_product_id,
                    "variation_id": pancake_variation_id,
                    "quantity": 1,
                    "variation_info": {"retail_price": float(base_price)},
                }
            ],
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/shops/{shop_id}/orders/get_promotion_advance_active",
                params={"api_key": api_key},
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}

    by_promotion_id: dict[str, float] = {}

    def _set_if_better(promotion_id: str, candidate: Optional[float]) -> None:
        if candidate is None:
            return
        if candidate >= base_price:
            return
        current = by_promotion_id.get(promotion_id)
        if current is None or candidate < current:
            by_promotion_id[promotion_id] = round(float(candidate), 2)

    rows = data.get("data") if isinstance(data, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            promotion_id = _to_text(row.get("promotion_advance_id") or row.get("promotion_id"))
            if not promotion_id:
                continue

            promo_info = row.get("promotion_advance_info") if isinstance(row.get("promotion_advance_info"), dict) else {}

            # 1) direct fields on row/promo info
            direct_price = _extract_first_positive_number(
                row.get("discounted_price"),
                row.get("price_after_discount"),
                promo_info.get("discounted_price"),
                promo_info.get("price_after_discount"),
            )
            if direct_price is not None:
                _set_if_better(promotion_id, direct_price)

            # 2) promotion-level coupon/promo code info
            coupon_info = promo_info.get("coupon_info") if isinstance(promo_info.get("coupon_info"), dict) else {}
            promo_code_info = promo_info.get("promo_code_info") if isinstance(promo_info.get("promo_code_info"), dict) else {}
            promo_discount = _extract_first_positive_number(coupon_info.get("discount"), promo_code_info.get("discount"))
            promo_is_percent = bool(coupon_info.get("is_percent") or promo_code_info.get("is_percent"))
            promo_max_pct = _extract_first_positive_number(coupon_info.get("max_discount_by_percent"), promo_code_info.get("max_discount_by_percent"))
            if promo_discount is not None:
                if promo_is_percent:
                    pct = max(0.0, min(100.0, float(promo_discount)))
                    amount = base_price * (pct / 100.0)
                    if promo_max_pct is not None and amount > promo_max_pct:
                        amount = float(promo_max_pct)
                    _set_if_better(promotion_id, max(0.0, base_price - amount))
                else:
                    _set_if_better(promotion_id, max(0.0, base_price - float(promo_discount)))

            # 3) item-level info under promotion_advance_info.items[]
            items = promo_info.get("items") if isinstance(promo_info.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue

                fixed_price = _extract_first_positive_number(item.get("fixed_prices"))
                if fixed_price is not None and fixed_price > 0:
                    _set_if_better(promotion_id, fixed_price)

                coupon_item_info = item.get("coupon_item_info") if isinstance(item.get("coupon_item_info"), dict) else {}
                item_discount = _extract_first_positive_number(coupon_item_info.get("discount"))
                item_is_percent = bool(coupon_item_info.get("is_percent"))
                item_max_pct = _extract_first_positive_number(coupon_item_info.get("max_discount_by_percent"))
                if item_discount is not None:
                    if item_is_percent:
                        pct = max(0.0, min(100.0, float(item_discount)))
                        amount = base_price * (pct / 100.0)
                        if item_max_pct is not None and amount > item_max_pct:
                            amount = float(item_max_pct)
                        _set_if_better(promotion_id, max(0.0, base_price - amount))
                    else:
                        _set_if_better(promotion_id, max(0.0, base_price - float(item_discount)))

                level_info = item.get("level_info") if isinstance(item.get("level_info"), list) else []
                for level in level_info:
                    if not isinstance(level, dict):
                        continue
                    lv_discount = _extract_first_positive_number(level.get("discount"))
                    if lv_discount is None:
                        continue
                    lv_is_percent = bool(level.get("is_percent"))
                    if lv_is_percent:
                        pct = max(0.0, min(100.0, float(lv_discount)))
                        _set_if_better(promotion_id, base_price * (1.0 - (pct / 100.0)))
                    else:
                        _set_if_better(promotion_id, max(0.0, base_price - float(lv_discount)))

    return by_promotion_id


async def _fetch_active_promotion_rows(
    *,
    pancake_product_id: str,
    pancake_variation_id: str,
    base_price: float,
) -> list[dict[str, Any]]:
    base_url = (settings.PANCAKE_BASE_URL or "").rstrip("/")
    api_key = settings.PANCAKE_API_KEY
    shop_id = settings.PANCAKE_SHOP_ID
    if not (base_url and api_key and shop_id):
        return []

    shop_id_num = _to_int(shop_id)
    if shop_id_num is None:
        return []

    payload = {
        "order": {
            "shop_id": int(shop_id_num),
            "items": [
                {
                    "product_id": pancake_product_id,
                    "variation_id": pancake_variation_id,
                    "quantity": 1,
                    "variation_info": {"retail_price": float(base_price)},
                }
            ],
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/shops/{shop_id}/orders/get_promotion_advance_active",
                params={"api_key": api_key},
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _extract_best_discount_from_active_rows(rows: list[dict[str, Any]], base_price: float) -> Optional[float]:
    if not rows or base_price <= 0:
        return None

    best: Optional[float] = None

    def _set_if_better(candidate: Optional[float]) -> None:
        nonlocal best
        if candidate is None:
            return
        value = float(candidate)
        if value <= 0 or value >= base_price:
            return
        if best is None or value < best:
            best = value

    for row in rows:
        promo_info = row.get("promotion_advance_info") if isinstance(row.get("promotion_advance_info"), dict) else {}

        direct_price = _extract_first_positive_number(
            row.get("discounted_price"),
            row.get("price_after_discount"),
            promo_info.get("discounted_price"),
            promo_info.get("price_after_discount"),
        )
        _set_if_better(direct_price)

        coupon_info = promo_info.get("coupon_info") if isinstance(promo_info.get("coupon_info"), dict) else {}
        promo_code_info = promo_info.get("promo_code_info") if isinstance(promo_info.get("promo_code_info"), dict) else {}
        promo_discount = _extract_first_positive_number(coupon_info.get("discount"), promo_code_info.get("discount"))
        promo_is_percent = bool(coupon_info.get("is_percent") or promo_code_info.get("is_percent"))
        promo_max_pct = _extract_first_positive_number(coupon_info.get("max_discount_by_percent"), promo_code_info.get("max_discount_by_percent"))
        if promo_discount is not None:
            if promo_is_percent:
                pct = max(0.0, min(100.0, float(promo_discount)))
                amount = base_price * (pct / 100.0)
                if promo_max_pct is not None and amount > promo_max_pct:
                    amount = float(promo_max_pct)
                _set_if_better(max(0.0, base_price - amount))
            else:
                _set_if_better(max(0.0, base_price - float(promo_discount)))

        items = promo_info.get("items") if isinstance(promo_info.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue

            fixed_price = _extract_first_positive_number(item.get("fixed_prices"))
            _set_if_better(fixed_price)

            coupon_item_info = item.get("coupon_item_info") if isinstance(item.get("coupon_item_info"), dict) else {}
            item_discount = _extract_first_positive_number(coupon_item_info.get("discount"))
            item_is_percent = bool(coupon_item_info.get("is_percent"))
            item_max_pct = _extract_first_positive_number(coupon_item_info.get("max_discount_by_percent"))
            if item_discount is not None:
                if item_is_percent:
                    pct = max(0.0, min(100.0, float(item_discount)))
                    amount = base_price * (pct / 100.0)
                    if item_max_pct is not None and amount > item_max_pct:
                        amount = float(item_max_pct)
                    _set_if_better(max(0.0, base_price - amount))
                else:
                    _set_if_better(max(0.0, base_price - float(item_discount)))

            level_info = item.get("level_info") if isinstance(item.get("level_info"), list) else []
            for level in level_info:
                if not isinstance(level, dict):
                    continue
                lv_discount = _extract_first_positive_number(level.get("discount"))
                if lv_discount is None:
                    continue
                lv_is_percent = bool(level.get("is_percent"))
                if lv_is_percent:
                    pct = max(0.0, min(100.0, float(lv_discount)))
                    _set_if_better(base_price * (1.0 - (pct / 100.0)))
                else:
                    _set_if_better(max(0.0, base_price - float(lv_discount)))

    return round(float(best), 2) if best is not None else None


async def _resolve_active_discount_prices_by_variant(product: Product) -> dict[int, float]:
    pancake_product_id = _to_text(getattr(product, "pancake_product_id", None))
    if not pancake_product_id:
        return {}

    variants = [v for v in (product.variants or []) if getattr(v, "is_active", True)]
    if not variants:
        return {}

    result: dict[int, float] = {}

    async def _resolve_one(variant: Any) -> tuple[int, Optional[float]]:
        variant_id = _to_int(getattr(variant, "id", None), 0) or 0
        pancake_variation_id = _to_text(getattr(variant, "pancake_variation_id", None))
        if variant_id <= 0 or not pancake_variation_id:
            return variant_id, None

        base_price = _to_float(getattr(variant, "sale_price", None)) or _to_float(getattr(variant, "price", None))
        if base_price is None:
            base_price = _to_float(getattr(product, "sale_price", None)) or _to_float(getattr(product, "price", None)) or 0.0
        if base_price <= 0:
            return variant_id, None

        rows = await _fetch_active_promotion_rows(
            pancake_product_id=pancake_product_id,
            pancake_variation_id=pancake_variation_id,
            base_price=float(base_price),
        )
        best = _extract_best_discount_from_active_rows(rows, float(base_price))
        return variant_id, best

    for variant_id, discounted in await asyncio.gather(*[_resolve_one(v) for v in variants]):
        if variant_id <= 0:
            continue
        if discounted is None:
            continue
        result[int(variant_id)] = float(discounted)

    return result


def _inject_computed_promotion_prices(payload: dict[str, Any], prices_by_promotion_id: dict[str, float]) -> dict[str, Any]:
    if not prices_by_promotion_id:
        return payload

    enriched = dict(payload)
    promotions = list(_iter_dicts(enriched.get("promotions")))
    updated_promotions: list[dict[str, Any]] = []

    for promotion in promotions:
        promo_id = _to_text(
            promotion.get("id")
            or promotion.get("promotion_id")
            or promotion.get("promotion_advance_id")
            or (promotion.get("promotion_product") or {}).get("id") if isinstance(promotion.get("promotion_product"), dict) else None
        )
        discounted_price = prices_by_promotion_id.get(str(promo_id)) if promo_id else None
        if discounted_price is None:
            updated_promotions.append(promotion)
            continue

        p = dict(promotion)
        if isinstance(p.get("promotion_product"), dict):
            pp = dict(p["promotion_product"])
            pp["discounted_price"] = discounted_price
            p["promotion_product"] = pp
        p["discounted_price"] = discounted_price
        updated_promotions.append(p)

    if updated_promotions:
        enriched["promotions"] = updated_promotions
    return enriched


async def _fetch_live_promotions_by_ids(promotion_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not promotion_ids:
        return {}

    base_url = (settings.PANCAKE_BASE_URL or "").rstrip("/")
    api_key = settings.PANCAKE_API_KEY
    shop_id = settings.PANCAKE_SHOP_ID
    if not (base_url and api_key and shop_id):
        return {}

    found: dict[str, dict[str, Any]] = {}
    page = 1
    page_size = 100

    while page <= 10 and len(found) < len(promotion_ids):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{base_url}/shops/{shop_id}/promotion_advance",
                    params={
                        "api_key": api_key,
                        "page": page,
                        "page_size": page_size,
                    },
                )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            break

        if not isinstance(payload, dict):
            break
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue
            promo = row.get("promotion_product") if isinstance(row.get("promotion_product"), dict) else row
            if not isinstance(promo, dict):
                continue
            pid = _to_text(promo.get("id") or row.get("id") or row.get("promotion_id"))
            if pid and pid in promotion_ids:
                found[pid] = promo

        if len(rows) < page_size:
            break
        total_pages = _to_int(payload.get("total_pages"), 0) or 0
        if total_pages and page >= total_pages:
            break
        page += 1

    return found


def _merge_live_promotion_definitions(payload: dict[str, Any], live_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not live_by_id:
        return payload

    enriched = dict(payload)
    promotions = list(_iter_dicts(enriched.get("promotions")))
    merged_promotions: list[dict[str, Any]] = []

    for promotion in promotions:
        p = dict(promotion)
        promotion_obj = p.get("promotion_product") if isinstance(p.get("promotion_product"), dict) else p
        pid = _to_text(
            (promotion_obj or {}).get("id")
            or p.get("id")
            or p.get("promotion_id")
            or p.get("promotion_advance_id")
        )
        if not pid or pid not in live_by_id:
            merged_promotions.append(p)
            continue

        live = dict(live_by_id[pid])
        if isinstance(p.get("promotion_product"), dict):
            current = dict(p.get("promotion_product") or {})
            current.update(live)
            p["promotion_product"] = current
        else:
            p.update(live)

        merged_promotions.append(p)

    if merged_promotions:
        enriched["promotions"] = merged_promotions
    return enriched


def _build_combo_offers(product: Product, linked_products_by_pancake_id: dict[str, Product]) -> list[ProductComboOffer]:
    payload = product.pancake_payload if isinstance(product.pancake_payload, dict) else {}
    raw_items = _collect_combo_candidates(payload)
    if not raw_items:
        return []

    combo_items: list[ProductComboItem] = []
    for raw_item in raw_items:
        nested = _first_present_dict(raw_item.get("product"), raw_item.get("item"), raw_item.get("variation")) or {}
        pancake_product_id = _extract_combo_pancake_product_id(raw_item)
        linked = linked_products_by_pancake_id.get(str(pancake_product_id)) if pancake_product_id else None

        quantity = _to_int(
            raw_item.get("quantity")
            or raw_item.get("qty")
            or raw_item.get("amount")
            or nested.get("quantity")
            or nested.get("qty")
            or 1
        ) or 1
        if quantity < 1:
            quantity = 1

        label = (
            _to_text(raw_item.get("name"))
            or _to_text(raw_item.get("title"))
            or _to_text(raw_item.get("product_name"))
            or _to_text(nested.get("name"))
            or _to_text(nested.get("title"))
            or (linked.name if linked is not None else None)
            or "San pham combo"
        )

        image = (
            _to_text(raw_item.get("image"))
            or _to_text(raw_item.get("image_url"))
            or _to_text(nested.get("image"))
            or _to_text(nested.get("image_url"))
            or (linked.thumbnail if linked is not None else None)
        )

        price = (
            _to_float(raw_item.get("price"))
            or _to_float(raw_item.get("sale_price"))
            or _to_float(raw_item.get("retail_price"))
            or _to_float(nested.get("price"))
            or (_to_float(linked.sale_price) if linked is not None else None)
            or (_to_float(linked.price) if linked is not None else None)
        )

        combo_items.append(
            ProductComboItem(
                label=label,
                quantity=quantity,
                pancakeProductId=pancake_product_id,
                localProductId=(str(linked.id) if linked is not None else None),
                localProductSlug=(str(linked.slug) if linked is not None else None),
                image=image,
                price=price,
                required=bool(raw_item.get("required") or raw_item.get("is_required") or raw_item.get("is_mandatory")),
            )
        )

    if not combo_items:
        return []

    offer_title = _to_text(payload.get("combo_title")) or _to_text(payload.get("promotion_title")) or "Combo gợi ý"
    offer_description = _to_text(payload.get("combo_description")) or _to_text(payload.get("promotion_description"))
    return [ProductComboOffer(title=offer_title, description=offer_description, items=combo_items)]


def _build_promotion_offers(product: Product, linked_products_by_pancake_id: dict[str, Product]) -> list[ProductPromotionOffer]:
    payload = product.pancake_payload if isinstance(product.pancake_payload, dict) else {}
    raw_promotions = _collect_promotion_candidates(payload)
    if not raw_promotions:
        return []

    offers: list[ProductPromotionOffer] = []
    for raw in raw_promotions:
        if not isinstance(raw, dict):
            continue

        promotion_obj = _first_present_dict(raw.get("promotion_product"), raw) or {}
        if not isinstance(promotion_obj, dict):
            continue

        promo_id = _to_text(
            promotion_obj.get("id")
            or raw.get("id")
            or raw.get("promotion_id")
            or raw.get("promotion_advance_id")
        )
        promo_title = _to_text(promotion_obj.get("name") or raw.get("name")) or "Khuyến mãi"
        promo_description = _to_text(
            promotion_obj.get("description")
            or promotion_obj.get("note")
            or raw.get("description")
            or raw.get("note")
        )
        promotion_type = _to_text(
            promotion_obj.get("type")
            or promotion_obj.get("program_type")
            or promotion_obj.get("action_type")
            or promotion_obj.get("discount_type")
        )
        promotion_kind = _infer_promotion_kind(promotion_type, promotion_obj)
        starts_at = _to_text(
            promotion_obj.get("start_date")
            or promotion_obj.get("start_time")
            or raw.get("start_date")
            or raw.get("start_time")
        )
        ends_at = _to_text(
            promotion_obj.get("end_date")
            or promotion_obj.get("end_time")
            or raw.get("end_date")
            or raw.get("end_time")
        )

        promotion_items: list[ProductPromotionItem] = []
        for item in _collect_promotion_items(promotion_obj):
            nested = _first_present_dict(item.get("product"), item.get("item"), item.get("variation")) or {}
            variation_info = item.get("variation_info") if isinstance(item.get("variation_info"), dict) else {}
            pancake_product_id = _extract_combo_pancake_product_id(item)
            linked = linked_products_by_pancake_id.get(str(pancake_product_id)) if pancake_product_id else None

            quantity = _to_int(
                item.get("quantity")
                or item.get("qty")
                or item.get("amount")
                or item.get("count")
                or nested.get("quantity")
                or nested.get("qty")
                or nested.get("count")
                or 1
            ) or 1
            if quantity < 1:
                quantity = 1

            label = (
                _to_text(item.get("name"))
                or _to_text(item.get("title"))
                or _to_text(item.get("product_name"))
                or _to_text(nested.get("name"))
                or _to_text(nested.get("title"))
                or (linked.name if linked is not None else None)
                or "Sản phẩm khuyến mãi"
            )
            image = (
                _to_text(item.get("image"))
                or _to_text(item.get("image_url"))
                or _to_text(nested.get("image"))
                or _to_text(nested.get("image_url"))
                or (linked.thumbnail if linked is not None else None)
            )
            price = (
                _to_float(item.get("price"))
                or _to_float(item.get("sale_price"))
                or _to_float(item.get("retail_price"))
                or _to_float(variation_info.get("retail_price"))
                or _to_float(nested.get("price"))
                or (_to_float(linked.sale_price) if linked is not None else None)
                or (_to_float(linked.price) if linked is not None else None)
            )

            discounted_price = _estimate_discounted_price(
                base_price=price,
                promotion=promotion_obj,
                item=item,
                nested=nested,
            )
            if discounted_price is not None:
                price = discounted_price

            promotion_items.append(
                ProductPromotionItem(
                    label=label,
                    quantity=quantity,
                    pancakeProductId=pancake_product_id,
                    localProductId=(str(linked.id) if linked is not None else None),
                    localProductSlug=(str(linked.slug) if linked is not None else None),
                    image=image,
                    price=price,
                )
            )

        if not promotion_items:
            promotion_items.append(
                ProductPromotionItem(
                    label=str(getattr(product, "name", "Sản phẩm")),
                    quantity=1,
                    pancakeProductId=(str(getattr(product, "pancake_product_id", "") or "") or None),
                    localProductId=(str(getattr(product, "id", "") or "") or None),
                    localProductSlug=(str(getattr(product, "slug", "") or "") or None),
                    image=_resolve_storefront_thumbnail(product),
                    price=_to_float(getattr(product, "sale_price", None)) or _to_float(getattr(product, "price", None)),
                )
            )

        offers.append(
            ProductPromotionOffer(
                id=promo_id,
                title=promo_title,
                description=promo_description,
                promotionType=promotion_type,
                promotionKind=promotion_kind,
                startsAt=starts_at,
                endsAt=ends_at,
                meta=_build_promotion_meta(promotion_obj, promotion_type, promotion_kind),
                items=promotion_items,
            )
        )

    return offers


def _product_to_item(
    product: Product,
    category: Category,
    rating_summary: Optional[ProductReviewSummary] = None,
) -> PublicProductItem:
    thumbnail = _resolve_storefront_thumbnail(product)
    created_at = getattr(product, "created_at", None) or datetime.now(timezone.utc)
    updated_at = getattr(product, "updated_at", None) or created_at

    return PublicProductItem(
        id=str(product.id),
        name=str(getattr(product, "name", None) or f"Product {product.id}"),
        slug=str(getattr(product, "slug", None) or f"product-{product.id}"),
        price=float(_to_float(getattr(product, "price", None)) or 0.0),
        originalPrice=_to_float(getattr(product, "original_price", None)),
        thumbnail=thumbnail,
        stock=int(_to_int(getattr(product, "stock", None)) or 0),
        status=_normalize_status(product),
        category={"id": str(category.id), "name": str(getattr(category, "name", None) or "Danh muc")},
        ratingSummary=(rating_summary or ProductReviewSummary()).model_dump(),
        createdAt=created_at,
        updatedAt=updated_at,
    )


def _product_to_detail(
    product: Product,
    category: Category,
    linked_products_by_pancake_id: Optional[dict[str, Product]] = None,
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
        payload = getattr(v, "pancake_payload", None)
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

    combo_offers = _build_combo_offers(product, linked_products_by_pancake_id or {})
    promotion_offers = _build_promotion_offers(product, linked_products_by_pancake_id or {})

    return PublicProductDetail(
        **detail_base,
        shortDescription=getattr(product, "short_description", None),
        description=getattr(product, "description", None),
        currency=getattr(product, "currency", "VND"),
        salePrice=_to_float(getattr(product, "sale_price", None)),
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
        images=images,
        variants=variants,
        comboOffers=combo_offers,
        promotionOffers=promotion_offers,
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

    linked_products_by_pancake_id: dict[str, Product] = {}
    payload = product.pancake_payload if isinstance(product.pancake_payload, dict) else {}

    promotion_ids = {
        str(pid)
        for promo in _collect_promotion_candidates(payload)
        for pid in [_to_text(promo.get("id") or promo.get("promotion_id") or promo.get("promotion_advance_id") or ((promo.get("promotion_product") or {}).get("id") if isinstance(promo.get("promotion_product"), dict) else None))]
        if pid
    }
    if promotion_ids:
        live_promotions = await _fetch_live_promotions_by_ids(promotion_ids)
        if live_promotions:
            payload = _merge_live_promotion_definitions(payload, live_promotions)
            product.pancake_payload = payload

    active_discount_prices = await _resolve_active_discounted_prices(product)
    if active_discount_prices:
        payload = _inject_computed_promotion_prices(payload, active_discount_prices)
        product.pancake_payload = payload

    variant_discount_prices = await _resolve_active_discount_prices_by_variant(product)
    if variant_discount_prices:
        for variant in product.variants or []:
            variant_id = _to_int(getattr(variant, "id", None), 0) or 0
            discounted = variant_discount_prices.get(int(variant_id)) if variant_id > 0 else None
            if discounted is None:
                continue
            current_sale = _to_float(getattr(variant, "sale_price", None))
            if current_sale is None or discounted < current_sale:
                variant.sale_price = float(discounted)

        min_variant_discount = min(variant_discount_prices.values())
        product_sale = _to_float(getattr(product, "sale_price", None))
        if product_sale is None or min_variant_discount < product_sale:
            product.sale_price = float(min_variant_discount)

    raw_combo_items = _collect_combo_candidates(payload)
    raw_promotions = _collect_promotion_candidates(payload)
    pancake_product_ids = sorted({
        str(pid)
        for pid in (_extract_combo_pancake_product_id(item) for item in raw_combo_items)
        if pid
    })
    promotion_product_ids = sorted({
        str(pid)
        for promotion in raw_promotions
        for pid in (
            _extract_combo_pancake_product_id(item)
            for item in _collect_promotion_items(
                _first_present_dict(promotion.get("promotion_product"), promotion) or {}
            )
        )
        if pid
    })
    linked_pancake_ids = sorted(set([*pancake_product_ids, *promotion_product_ids]))
    if linked_pancake_ids:
        linked_rows = await db.execute(
            select(Product).where(
                Product.pancake_product_id.in_(linked_pancake_ids),
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
        )
        linked_products_by_pancake_id = {
            str(linked.pancake_product_id): linked
            for linked in linked_rows.scalars().all()
            if getattr(linked, "pancake_product_id", None)
        }

    detail = _product_to_detail(product, category, linked_products_by_pancake_id)
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
            Order.status == OrderStatus.DELIVERED.value,
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
