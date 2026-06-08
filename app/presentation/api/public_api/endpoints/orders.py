from __future__ import annotations

import logging
import random
import json
from types import SimpleNamespace
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.public_order import (
    PublicOrderCreateBody,
    PublicOrderCreateResponse,
    PublicOrderItemResponse,
    PublicOrderLookupResponse,
    PublicOrderResponseData,
)
from app.application.services.pancake_order_service import PancakeOrderService, PancakeOrderSyncError
from app.core.config import settings
from app.core.deps import get_db
from app.domain.models.order import Order, OrderStatus
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductVariant
from app.domain.models.user import User
from app.presentation.api.public_api.deps import get_optional_account_user
from app.presentation.api.public_api.endpoints.products import _estimate_discounted_price
from app.services.email_service import send_order_email_flow


router = APIRouter(prefix='/orders', tags=['Public Orders'])
pancake_order_service = PancakeOrderService()
logger = logging.getLogger(__name__)


def _build_tracking_code() -> str:
    # Format: MMYYMMDDXXXXXX
    stamp = datetime.utcnow().strftime('%y%m%d')
    random_part = f"{random.randint(0, 999999):06d}"
    return f'MM{stamp}{random_part}'


def _normalize_status(raw: object) -> str:
    if isinstance(raw, OrderStatus):
        return raw.value
    return str(raw or 'pending')


def _coerce_dict(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {}


def _coerce_dict_list(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _pick_first_non_empty(source: dict, keys: tuple[str, ...]) -> Optional[object]:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        return value
    return None


def _coerce_json_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _extract_nested_object(source: dict[str, Any]) -> dict[str, Any]:
    for key in ('product', 'item', 'variation'):
        value = source.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _identifier_set(source: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            result.add(normalized)
    return result


def _promotion_item_matches_product(
    item: dict[str, Any],
    nested: dict[str, Any],
    product_keys: set[str],
) -> bool:
    item_keys = _identifier_set(
        item,
        (
            'local_product_id',
            'product_local_id',
            'product_id',
            'productId',
            'pancake_product_id',
            'pancakeProductId',
            'id',
        ),
    )
    nested_keys = _identifier_set(
        nested,
        (
            'local_product_id',
            'product_local_id',
            'product_id',
            'productId',
            'pancake_product_id',
            'pancakeProductId',
            'id',
        ),
    )
    candidates = item_keys | nested_keys
    if not candidates:
        return True
    return bool(candidates & product_keys)


def _promotion_item_matches_variant(
    item: dict[str, Any],
    nested: dict[str, Any],
    variant_keys: set[str],
) -> bool:
    item_keys = _identifier_set(
        item,
        (
            'local_variant_id',
            'variant_local_id',
            'variant_id',
            'variantId',
            'product_variant_id',
            'productVariantId',
            'variation_id',
            'variationId',
            'pancake_variation_id',
            'pancakeVariationId',
        ),
    )
    nested_keys = _identifier_set(
        nested,
        (
            'local_variant_id',
            'variant_local_id',
            'variant_id',
            'variantId',
            'product_variant_id',
            'productVariantId',
            'variation_id',
            'variationId',
            'pancake_variation_id',
            'pancakeVariationId',
            'id',
        ),
    )
    candidates = item_keys | nested_keys
    if not candidates:
        return True
    if not variant_keys:
        return False
    return bool(candidates & variant_keys)


def _collect_promotion_items(promotion: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in (
        'items',
        'products',
        'applied_products',
        'variations',
        'bonus_items',
        'bonus_products',
        'free_products',
        'gift_products',
        'combo_products',
        'combo_items',
    ):
        raw_items = promotion.get(key)
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if isinstance(raw, dict):
                items.append(raw)
    return items


def _resolve_promotional_unit_price(
    *,
    product: Product,
    selected_variant: Optional[ProductVariant],
    quantity: int,
    base_unit_price: float,
) -> float:
    if base_unit_price <= 0:
        return 0.0

    payload = _coerce_json_dict(getattr(product, 'pancake_payload', None))
    promotions = payload.get('promotions') if isinstance(payload.get('promotions'), list) else []
    if not promotions:
        return round(base_unit_price, 2)

    product_keys = {
        str(product.id).strip(),
        str(getattr(product, 'pancake_product_id', '') or '').strip(),
    }
    product_keys = {key for key in product_keys if key}

    variant_keys: set[str] = set()
    if selected_variant is not None:
        variant_keys = {
            str(getattr(selected_variant, 'id', '') or '').strip(),
            str(getattr(selected_variant, 'pancake_variation_id', '') or '').strip(),
        }
        variant_keys = {key for key in variant_keys if key}

    best_price = float(base_unit_price)

    for promotion in promotions:
        if not isinstance(promotion, dict):
            continue

        nested = promotion.get('promotion_product') if isinstance(promotion.get('promotion_product'), dict) else {}
        candidate_items = _collect_promotion_items(promotion)
        if not candidate_items:
            candidate_items = [nested or {}]

        for raw_item in candidate_items:
            item = dict(raw_item)
            nested_item = _extract_nested_object(item)
            if not _promotion_item_matches_product(item, nested_item, product_keys):
                continue
            if not _promotion_item_matches_variant(item, nested_item, variant_keys):
                continue

            item.setdefault('quantity', max(1, int(quantity)))
            estimated = _estimate_discounted_price(
                base_price=base_unit_price,
                promotion=promotion,
                item=item,
                nested=(nested if isinstance(nested, dict) else {}),
            )
            if estimated is None:
                continue
            if 0 < float(estimated) < best_price:
                best_price = float(estimated)

    return round(best_price, 2)


def _extract_pancake_webhook_order(payload: dict) -> tuple[Optional[str], Optional[object], Optional[str], dict]:
    if not isinstance(payload, dict):
        return None, None, None, {}

    data = _coerce_dict(payload.get('data')) or payload
    nested_order = _coerce_dict(data.get('order'))
    nested_orders = _coerce_dict_list(data.get('orders'))
    first_nested_order = nested_orders[0] if nested_orders else {}

    candidate_sources = [
        payload,
        _coerce_dict(payload.get('data')),
        _coerce_dict(payload.get('order')),
        data,
        nested_order,
        first_nested_order,
    ]

    id_keys = ('id', 'order_id', 'orderId', 'display_id', 'displayId', 'reference_id', 'referenceId')
    status_keys = ('status', 'order_status', 'orderStatus', 'state', 'status_text', 'statusText')
    custom_id_keys = ('custom_id', 'customId', 'tracking_code', 'trackingCode', 'code')

    pancake_order_id = None
    for source in candidate_sources:
        pancake_order_id = _pick_first_non_empty(source, id_keys)
        if pancake_order_id is not None:
            break

    status_value = None
    for source in candidate_sources:
        status_value = _pick_first_non_empty(source, status_keys)
        if status_value is not None:
            break

    custom_id = None
    for source in candidate_sources:
        custom_id = _pick_first_non_empty(source, custom_id_keys)
        if custom_id is not None:
            break

    return (
        str(pancake_order_id) if pancake_order_id is not None else None,
        status_value,
        str(custom_id) if custom_id else None,
        data or payload,
    )


def _try_parse_webhook_payload(raw_body: bytes) -> tuple[Optional[dict], Optional[str]]:
    text = raw_body.decode('utf-8', errors='ignore').strip()
    if not text:
        return None, 'EMPTY_BODY'

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0], None
    except Exception:
        pass

    form = parse_qs(text, keep_blank_values=True)
    if not form:
        return None, 'UNSUPPORTED_PAYLOAD_FORMAT'

    candidate_keys = ('data', 'payload', 'event', 'order', 'orders')
    for key in candidate_keys:
        values = form.get(key)
        if not values:
            continue
        first = (values[0] or '').strip()
        if not first:
            continue
        try:
            parsed = json.loads(first)
            if isinstance(parsed, dict):
                return parsed, None
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0], None
        except Exception:
            continue

    fallback = {k: (v[0] if isinstance(v, list) and v else v) for k, v in form.items()}
    return fallback, None


def _extract_related_ids(payload: dict, data: dict) -> set[str]:
    result: set[str] = set()

    sources = [
        payload,
        _coerce_dict(payload.get('data')),
        _coerce_dict(payload.get('order')),
        data,
        _coerce_dict(data.get('order')),
    ]

    for item in _coerce_dict_list(payload.get('orders')):
        sources.append(item)
    for item in _coerce_dict_list(data.get('orders')):
        sources.append(item)

    id_keys = ('id', 'order_id', 'orderId', 'display_id', 'displayId', 'reference_id', 'referenceId')
    candidates: list[object] = []
    for source in sources:
        for key in id_keys:
            if key in source:
                candidates.append(source.get(key))

    for value in candidates:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            result.add(normalized)
    return result


def _extract_known_ids_from_saved_pancake_payload(raw_payload: object) -> set[str]:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    ids: set[str] = set()
    if not payload:
        return ids

    sources = [
        payload,
        _coerce_dict(payload.get('data')),
        _coerce_dict(payload.get('last_order_data')),
        _coerce_dict(payload.get('last_webhook')),
    ]

    for source in list(sources):
        nested_data = _coerce_dict(source.get('data'))
        nested_order = _coerce_dict(source.get('order'))
        if nested_data:
            sources.append(nested_data)
        if nested_order:
            sources.append(nested_order)
        for item in _coerce_dict_list(source.get('orders')):
            sources.append(item)

    id_keys = ('id', 'order_id', 'orderId', 'display_id', 'displayId', 'reference_id', 'referenceId')
    for source in sources:
        for key in id_keys:
            value = source.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                ids.add(normalized)

    return ids


def _extract_pancake_order_id_from_create_response(raw: object, expected_custom_id: Optional[str] = None) -> Optional[str]:
    payload = raw if isinstance(raw, dict) else {}
    if not payload:
        return None

    def is_order_like(source: dict) -> bool:
        if not source:
            return False
        return any(
            key in source
            for key in (
                'order_id',
                'orderId',
                'shop_order_id',
                'shopOrderId',
                'display_id',
                'displayId',
                'custom_id',
                'customId',
                'tracking_code',
                'trackingCode',
                'order_status',
                'status',
                'bill_full_name',
                'bill_phone_number',
                'bill_address',
                'items',
                'order_items',
            )
        )

    def custom_id_matches(source: dict) -> bool:
        expected = str(expected_custom_id or '').strip()
        if not expected:
            return True
        source_custom = _pick_first_non_empty(source, ('custom_id', 'customId', 'tracking_code', 'trackingCode'))
        if source_custom is None:
            return True
        return str(source_custom).strip() == expected

    high_priority_sources: list[dict] = []
    medium_priority_sources: list[dict] = []
    low_priority_sources: list[dict] = []

    data = _coerce_dict(payload.get('data'))
    payload_order = _coerce_dict(payload.get('order'))
    data_order = _coerce_dict(data.get('order'))
    result = _coerce_dict(payload.get('result'))
    result_order = _coerce_dict(result.get('order'))

    for src in (data_order, payload_order, result_order, result):
        if src:
            high_priority_sources.append(src)

    for key in ('orders', 'results', 'list', 'items'):
        for item in _coerce_dict_list(payload.get(key)):
            high_priority_sources.append(item)
        for item in _coerce_dict_list(data.get(key)):
            high_priority_sources.append(item)

    if is_order_like(data):
        medium_priority_sources.append(data)
    if is_order_like(payload):
        medium_priority_sources.append(payload)

    if data:
        low_priority_sources.append(data)
    low_priority_sources.append(payload)

    preferred_keys = (
        'order_id',
        'orderId',
        'shop_order_id',
        'shopOrderId',
        'id',
        'display_id',
        'displayId',
        'reference_id',
        'referenceId',
    )

    for source in high_priority_sources + medium_priority_sources + low_priority_sources:
        if not is_order_like(source):
            continue
        if not custom_id_matches(source):
            continue
        candidate = _pick_first_non_empty(source, preferred_keys)
        if candidate is not None:
            normalized = str(candidate).strip()
            if normalized:
                return normalized
    return None


def _item_to_response(item: OrderItem) -> PublicOrderItemResponse:
    name = getattr(getattr(item, 'product', None), 'name', None) or f'Product #{item.product_id}'
    sku = None
    if getattr(item, 'variant', None) is not None:
        sku = getattr(item.variant, 'sku', None)
    if not sku and getattr(item, 'product', None) is not None:
        sku = getattr(item.product, 'sku', None)

    return PublicOrderItemResponse(
        productId=int(item.product_id),
        productVariantId=(int(item.product_variant_id) if item.product_variant_id is not None else None),
        name=str(name),
        sku=sku,
        quantity=int(item.quantity),
        unitPrice=float(item.price or 0),
        subtotal=float(item.total or 0),
    )


def _item_dict_to_response(item: dict) -> PublicOrderItemResponse:
    product_id = _pick_first_non_empty(item, ('product_id', 'productId', 'id', 'item_id', 'itemId'))
    variant_id = _pick_first_non_empty(item, ('product_variant_id', 'productVariantId', 'variant_id', 'variantId', 'variation_id', 'variationId'))
    quantity = _pick_first_non_empty(item, ('quantity', 'qty', 'count', 'amount'))
    unit_price = _pick_first_non_empty(item, ('unit_price', 'unitPrice', 'price', 'selling_price'))
    subtotal = _pick_first_non_empty(item, ('subtotal', 'line_total', 'lineTotal', 'total', 'amount'))
    name = _pick_first_non_empty(item, ('name', 'title', 'product_name', 'productName', 'variation_name'))
    sku = _pick_first_non_empty(item, ('sku', 'item_sku', 'itemSku', 'code'))

    try:
        pid = int(product_id) if product_id is not None else 0
    except Exception:
        pid = 0
    try:
        pvid = int(variant_id) if variant_id is not None else None
    except Exception:
        pvid = None
    try:
        qty = max(1, int(quantity or 1))
    except Exception:
        qty = 1
    try:
        unit = float(unit_price or 0)
    except Exception:
        unit = 0.0
    try:
        sub = float(subtotal if subtotal is not None else (unit * qty))
    except Exception:
        sub = unit * qty

    return PublicOrderItemResponse(
        productId=pid,
        productVariantId=pvid,
        name=str(name or 'Product'),
        sku=(str(sku) if sku is not None else None),
        quantity=qty,
        unitPrice=unit,
        subtotal=sub,
    )


def _to_order_response(order: Order) -> PublicOrderResponseData:
    payload = order.pancake_payload if isinstance(order.pancake_payload, dict) else {}
    payload_data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    payload_order = payload_data.get('order') if isinstance(payload_data.get('order'), dict) else payload_data

    receiver_name = _pick_first_non_empty(payload_order if isinstance(payload_order, dict) else {}, ('bill_full_name', 'receiver_name', 'receiverName', 'customer_name', 'name'))
    receiver_phone = _pick_first_non_empty(payload_order if isinstance(payload_order, dict) else {}, ('bill_phone_number', 'receiver_phone', 'receiverPhone', 'phone'))
    receiver_address = _pick_first_non_empty(payload_order if isinstance(payload_order, dict) else {}, ('bill_address', 'receiver_address', 'receiverAddress', 'address', 'full_address'))
    total_amount = _pick_first_non_empty(payload_order if isinstance(payload_order, dict) else {}, ('total_amount', 'totalAmount', 'total', 'grand_total', 'grandTotal', 'cod'))

    payload_items: list[dict] = []
    if isinstance(payload_order, dict):
        for key in ('items', 'order_items', 'orderItems', 'products', 'line_items', 'lines'):
            payload_items = _coerce_dict_list(payload_order.get(key))
            if payload_items:
                break

    return PublicOrderResponseData(
        id=int(order.id),
        trackingCode=order.tracking_code,
        pancakeOrderId=order.pancake_order_id,
        status=_normalize_status(order.status),
        paymentStatus=str(order.payment_status or 'pending'),
        paymentMethod=str(order.payment_method or 'cod'),
        receiverName=(str(receiver_name) if receiver_name is not None else None),
        receiverPhone=(str(receiver_phone) if receiver_phone is not None else order.receiver_phone),
        receiverAddress=(str(receiver_address) if receiver_address is not None else None),
        totalAmount=float(total_amount or order.total_amount or 0),
        createdAt=order.created_at,
        items=[_item_dict_to_response(item) for item in payload_items],
    )


@router.post('', response_model=PublicOrderCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_public_order(
    body: PublicOrderCreateBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_account_user),
):
    if not body.items:
        raise HTTPException(status_code=400, detail='Order must have at least one item')

    requested_receiver_email = str(body.receiver_email or '').strip().lower()
    account_email = str(getattr(current_user, 'email', '') or '').strip().lower() if current_user is not None else ''
    receiver_email = requested_receiver_email or account_email or None

    try:
        product_ids = sorted({int(item.product_id) for item in body.items})
        products_rows = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {int(p.id): p for p in products_rows.scalars().all()}

        variant_ids = sorted({int(item.product_variant_id) for item in body.items if item.product_variant_id is not None})
        variants: dict[int, ProductVariant] = {}
        if variant_ids:
            variants_rows = await db.execute(select(ProductVariant).where(ProductVariant.id.in_(variant_ids)))
            variants = {int(v.id): v for v in variants_rows.scalars().all()}

        order_items: list[OrderItem] = []
        order_email_items: list[dict[str, object]] = []
        total_amount = 0.0

        for item in body.items:
            product = products.get(int(item.product_id))
            if product is None:
                raise HTTPException(status_code=404, detail=f'Product {item.product_id} not found')

            if getattr(product, 'status', 'active') != 'active' or not bool(getattr(product, 'is_active', True)):
                raise HTTPException(status_code=400, detail=f'Product {item.product_id} is not available')

            quantity = int(item.quantity)
            selected_variant: Optional[ProductVariant] = None
            unit_price = float(getattr(product, 'sale_price', None) or getattr(product, 'price', 0) or 0)

            if item.product_variant_id is not None:
                variant_stmt = select(ProductVariant).where(
                    ProductVariant.id == int(item.product_variant_id),
                    ProductVariant.product_id == int(product.id),
                )
                selected_variant = (await db.execute(variant_stmt)).scalar_one_or_none()
                if selected_variant is None:
                    raise HTTPException(status_code=400, detail=f'Variant {item.product_variant_id} does not belong to product {product.id}')
                if bool(getattr(selected_variant, 'is_active', True)) is False:
                    raise HTTPException(status_code=400, detail=f'Variant {item.product_variant_id} is not available')
                unit_price = float(
                    getattr(selected_variant, 'sale_price', None)
                    or getattr(selected_variant, 'price', None)
                    or unit_price
                )

                manage_stock = bool(getattr(selected_variant, 'manage_stock', True))
                allow_backorder = bool(getattr(selected_variant, 'allow_backorder', False))
                available_stock = int(getattr(selected_variant, 'stock', 0) or 0)
                if manage_stock and not allow_backorder and quantity > available_stock:
                    raise HTTPException(status_code=400, detail=f'Not enough stock for product {product.id}')

                if manage_stock:
                    # Allow negative stock when backorder is enabled.
                    selected_variant.stock = available_stock - quantity
                variants[int(selected_variant.id)] = selected_variant
            else:
                manage_stock = bool(getattr(product, 'manage_stock', True))
                allow_backorder = bool(getattr(product, 'allow_backorder', False))
                available_stock = int(getattr(product, 'stock', 0) or 0)
                if manage_stock and not allow_backorder and quantity > available_stock:
                    raise HTTPException(status_code=400, detail=f'Not enough stock for product {product.id}')
                if manage_stock:
                    # Allow negative stock when backorder is enabled.
                    product.stock = available_stock - quantity

            unit_price = _resolve_promotional_unit_price(
                product=product,
                selected_variant=selected_variant,
                quantity=quantity,
                base_unit_price=unit_price,
            )

            subtotal = round(unit_price * quantity, 2)
            total_amount += subtotal
            order_items.append(
                OrderItem(
                    product_id=int(product.id),
                    product_variant_id=(int(item.product_variant_id) if item.product_variant_id is not None else None),
                    pancake_variation_id=(
                        str(getattr(selected_variant, 'pancake_variation_id'))
                        if selected_variant is not None and getattr(selected_variant, 'pancake_variation_id', None)
                        else None
                    ),
                    quantity=quantity,
                    price=unit_price,
                    total=subtotal,
                )
            )

            display_name = str(getattr(product, 'name', '') or f'Product #{product.id}').strip()
            if selected_variant is not None:
                variant_label = str(
                    getattr(selected_variant, 'name', None)
                    or getattr(selected_variant, 'title', None)
                    or getattr(selected_variant, 'sku', None)
                    or ''
                ).strip()
                if variant_label:
                    display_name = f"{display_name} ({variant_label})"

            order_email_items.append(
                {
                    'name': display_name,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'subtotal': subtotal,
                }
            )

        tracking_code = _build_tracking_code()

        if not pancake_order_service.is_enabled() or not pancake_order_service.is_configured():
            raise HTTPException(status_code=503, detail='Pancake is not configured for checkout')

        draft_order = SimpleNamespace(
            id=None,
            tracking_code=tracking_code,
            note=body.note,
            receiver_name=body.receiver_name,
            receiver_phone=body.receiver_phone,
            receiver_address=body.receiver_address,
            receiver_province_id=body.receiver_province_id,
            receiver_district_id=body.receiver_district_id,
            receiver_ward_id=body.receiver_ward_id,
            shipping_fee=0,
        )

        try:
            pancake_result = await pancake_order_service.create_order(
                order=draft_order,
                items=order_items,
                products_by_id=products,
                variants_by_id=variants,
                receiver_province_name=body.receiver_province_name,
                receiver_district_name=body.receiver_district_name,
                receiver_ward_name=body.receiver_ward_name,
            )
        except PancakeOrderSyncError as exc:
            logger.exception("Pancake order sync failed for tracking_code=%s", tracking_code)
            raise HTTPException(status_code=502, detail=f'Failed to sync order to Pancake: {exc}')

        pancake_order_id = None
        if isinstance(pancake_result, dict):
            pancake_order_id = _extract_pancake_order_id_from_create_response(
                pancake_result,
                expected_custom_id=tracking_code,
            )

        if pancake_order_id:
            verified = await pancake_order_service.get_order_detail(
                str(pancake_order_id),
                expected_custom_id=tracking_code,
            )
            if not isinstance(verified, dict):
                recovered = await pancake_order_service.find_order_by_custom_id(tracking_code)
                if isinstance(recovered, dict):
                    recovered_id = _extract_pancake_order_id_from_create_response(
                        recovered,
                        expected_custom_id=tracking_code,
                    )
                    if recovered_id:
                        pancake_order_id = recovered_id
                        pancake_result = recovered

        if not pancake_order_id:
            raise HTTPException(status_code=502, detail='Pancake order sync succeeded but no Pancake order id was returned')

        order = Order(
            user_id=int(current_user.id) if current_user is not None else 0,
            status=OrderStatus.PENDING.value,
            total_amount=round(total_amount, 2),
            payment_method=body.payment_method,
            payment_status='pending',
            note=body.note,
            tracking_code=tracking_code,
            receiver_phone=body.receiver_phone,
            pancake_order_id=str(pancake_order_id),
            pancake_payload=(pancake_result if isinstance(pancake_result, dict) else {'data': pancake_result}),
        )

        db.add(order)
        await db.commit()

        background_tasks.add_task(
            send_order_email_flow,
            order_id=int(order.id),
            tracking_code=str(tracking_code),
            receiver_name=str(body.receiver_name),
            receiver_phone=str(body.receiver_phone),
            receiver_address=str(body.receiver_address),
            payment_method=str(body.payment_method),
            total_amount=round(total_amount, 2),
            items=order_email_items,
            receiver_email=receiver_email,
            pancake_order_id=(str(pancake_order_id) if pancake_order_id is not None else None),
        )

        return {'success': True, 'data': _to_order_response(order).model_dump(by_alias=True)}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to create order: {exc}')


@router.post('/pancake-webhook')
async def pancake_order_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    signature = request.headers.get('X-Pancake-Signature') or request.headers.get('X-Signature')
    token = request.headers.get('X-Webhook-Token') or request.headers.get('X-Pancake-Token')

    expected_token = str(settings.PANCAKE_WEBHOOK_TOKEN or '').strip()
    if expected_token and token != expected_token:
        logger.warning('Rejected Pancake webhook due to invalid token')
        raise HTTPException(status_code=401, detail='Invalid webhook token')

    if not pancake_order_service.verify_webhook_signature(
        body=body,
        signature_header=signature,
        secret=settings.PANCAKE_WEBHOOK_SECRET,
    ):
        logger.warning('Rejected Pancake webhook due to invalid signature')
        raise HTTPException(status_code=401, detail='Invalid webhook signature')

    try:
        payload, parse_error = _try_parse_webhook_payload(body)
        if payload is None:
            raise HTTPException(status_code=400, detail=f'Invalid webhook payload: {parse_error or "UNKNOWN"}')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid webhook payload')

    pancake_order_id, raw_status, custom_id, data = _extract_pancake_webhook_order(payload)
    if not pancake_order_id and not custom_id:
        return {'success': True, 'ignored': True, 'reason': 'MISSING_ORDER_ID'}

    next_status = pancake_order_service.pancake_status_to_local_status(raw_status)

    order_query = select(Order)
    if pancake_order_id and custom_id:
        order_query = order_query.where(
            (Order.pancake_order_id == pancake_order_id) | (Order.tracking_code == custom_id)
        )
    elif pancake_order_id:
        order_query = order_query.where(Order.pancake_order_id == pancake_order_id)
    else:
        order_query = order_query.where(Order.tracking_code == custom_id)

    order = (await db.execute(order_query.limit(1))).scalar_one_or_none()
    related_ids = _extract_related_ids(payload, data)
    if order is None:
        if related_ids:
            fallback_stmt = (
                select(Order)
                .where(Order.pancake_order_id.is_not(None), Order.deleted_at.is_(None))
                .order_by(Order.id.desc())
                .limit(200)
            )
            fallback_orders = (await db.execute(fallback_stmt)).scalars().all()
            for candidate in fallback_orders:
                candidate_id = str(candidate.pancake_order_id or '').strip()
                if candidate_id and candidate_id in related_ids:
                    order = candidate
                    break

    if order is None and related_ids:
        # Second fallback: match incoming Pancake IDs against IDs persisted inside pancake_payload.
        payload_stmt = (
            select(Order)
            .where(Order.pancake_payload.is_not(None), Order.deleted_at.is_(None))
            .order_by(Order.id.desc())
            .limit(500)
        )
        payload_candidates = (await db.execute(payload_stmt)).scalars().all()
        for candidate in payload_candidates:
            known_ids = _extract_known_ids_from_saved_pancake_payload(candidate.pancake_payload)
            if known_ids and related_ids.intersection(known_ids):
                order = candidate
                break

    if order is None:
        return {'success': True, 'ignored': True, 'reason': 'ORDER_NOT_FOUND'}

    order.status = next_status
    if pancake_order_id and not order.pancake_order_id:
        order.pancake_order_id = pancake_order_id

    existing_payload = order.pancake_payload if isinstance(order.pancake_payload, dict) else {}
    existing_payload['last_webhook'] = payload
    existing_payload['last_order_data'] = data
    existing_payload['last_synced_status'] = next_status
    existing_payload['last_synced_at'] = datetime.utcnow().isoformat()
    order.pancake_payload = existing_payload

    await db.commit()
    return {
        'success': True,
        'updated': True,
        'order_id': int(order.id),
        'pancake_order_id': order.pancake_order_id,
        'status': next_status,
    }


@router.get('/lookup', response_model=PublicOrderLookupResponse)
async def lookup_public_order(
    tracking_code: str = Query(..., alias='trackingCode', min_length=4),
    phone: str = Query(..., min_length=4),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.items).selectinload(OrderItem.variant),
        )
        .where(Order.tracking_code == tracking_code)
        .limit(1)
    )
    order = (await db.execute(query)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail='Order not found')

    stored_phone = ''.join(ch for ch in str(order.receiver_phone or '') if ch.isdigit() or ch == '+')
    requested_phone = ''.join(ch for ch in str(phone or '') if ch.isdigit() or ch == '+')
    if stored_phone != requested_phone:
        raise HTTPException(status_code=403, detail='Phone number does not match order')

    return {'success': True, 'data': _to_order_response(order).model_dump(by_alias=True)}


@router.get('/pancake-addresses/provinces')
async def list_pancake_provinces():
    if not pancake_order_service.is_enabled() or not pancake_order_service.is_configured():
        return {'success': True, 'data': []}

    data = await pancake_order_service.list_provinces()
    return {'success': True, 'data': data, 'count': len(data)}


@router.get('/pancake-addresses/districts')
async def list_pancake_districts(
    province_id: Optional[int] = Query(None, alias='provinceId'),
):
    if not pancake_order_service.is_enabled() or not pancake_order_service.is_configured():
        return {'success': True, 'data': []}

    data = await pancake_order_service.list_districts(province_id=province_id)
    return {'success': True, 'data': data, 'count': len(data)}


@router.get('/pancake-addresses/communes')
async def list_pancake_communes(
    district_id: Optional[int] = Query(None, alias='districtId'),
):
    if not pancake_order_service.is_enabled() or not pancake_order_service.is_configured():
        return {'success': True, 'data': []}

    data = await pancake_order_service.list_communes(district_id=district_id)
    return {'success': True, 'data': data, 'count': len(data)}
