from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.admin_order import AdminBulkOrdersBody, AdminOrderUpdateBody
from app.application.services.pancake_order_service import PancakeOrderService, PancakeOrderSyncError
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.domain.models.order import Order
from app.domain.models.order_item import OrderItem
from app.domain.models.user import User


router = APIRouter()
pancake_order_service = PancakeOrderService()
logger = logging.getLogger(__name__)


def _normalize_status(value: object) -> str:
    if value is None:
        return 'pending'
    raw = getattr(value, 'value', value)
    return str(raw).strip().lower() or 'pending'


def _coerce_order_status(value: object) -> str:
    normalized = _normalize_status(value)
    if normalized in ('pending', 'processing', 'shipped', 'delivered', 'cancelled'):
        return normalized
    return pancake_order_service.pancake_status_to_local_status(normalized)


def _looks_like_local_tracking(value: str) -> bool:
    s = str(value or '').strip()
    return bool(s) and s.upper().startswith('MM')


def _extract_pancake_id_from_object(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    candidates = [
        payload.get('id'),
        payload.get('order_id'),
        payload.get('display_id'),
    ]
    nested_data = payload.get('data') if isinstance(payload.get('data'), dict) else None
    if nested_data is not None:
        candidates.extend([
            nested_data.get('id'),
            nested_data.get('order_id'),
            nested_data.get('display_id'),
        ])

    for candidate in candidates:
        if candidate is None:
            continue
        normalized = str(candidate).strip()
        if not normalized:
            continue
        if _looks_like_local_tracking(normalized):
            continue
        return normalized

    return None


def _resolve_pancake_order_id(order: Order) -> Optional[str]:
    raw = str(order.pancake_order_id or '').strip()
    if raw and not _looks_like_local_tracking(raw):
        return raw

    payload = order.pancake_payload if isinstance(order.pancake_payload, dict) else {}
    for source in (
        payload,
        payload.get('data'),
        payload.get('last_order_data'),
        payload.get('last_webhook'),
    ):
        resolved = _extract_pancake_id_from_object(source)
        if resolved:
            order.pancake_order_id = resolved
            return resolved

    return None


def _mark_order_detached_from_pancake(order: Order, *, reason: str) -> None:
    payload = order.pancake_payload if isinstance(order.pancake_payload, dict) else {}
    detached = {
        'reason': str(reason or 'UNKNOWN'),
        'detached_at': datetime.utcnow().isoformat(),
        'previous_pancake_order_id': str(order.pancake_order_id or '').strip() or None,
    }
    payload['pancake_detached'] = detached
    order.pancake_payload = payload
    order.pancake_order_id = None


def _to_order_summary(order: Order) -> dict:
    items = list(order.items or [])
    first_item = items[0] if items else None

    first_product_name = None
    if first_item and getattr(first_item, 'product', None) is not None:
        first_product_name = first_item.product.name

    payload = order.pancake_payload if isinstance(order.pancake_payload, dict) else {}
    payload_data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    payload_order = payload_data.get('order') if isinstance(payload_data.get('order'), dict) else payload_data
    receiver_name = None
    if isinstance(payload_order, dict):
        receiver_name = payload_order.get('bill_full_name') or payload_order.get('receiver_name') or payload_order.get('customer_name')

    return {
        'id': int(order.id),
        'tracking_code': order.tracking_code,
        'receiver_name': receiver_name,
        'receiver_phone': order.receiver_phone,
        'status': _normalize_status(order.status),
        'payment_status': str(order.payment_status or 'pending').lower(),
        'payment_method': str(order.payment_method or 'cod').lower(),
        'total_amount': float(order.total_amount or 0),
        'item_count': len(items),
        'first_product_name': first_product_name,
        'created_at': order.created_at,
        'updated_at': order.updated_at,
    }


def _to_order_detail(order: Order) -> dict:
    summary = _to_order_summary(order)

    summary['items'] = [
        {
            'id': int(item.id),
            'product_id': int(item.product_id),
            'product_variant_id': (int(item.product_variant_id) if item.product_variant_id is not None else None),
            'product_name': getattr(getattr(item, 'product', None), 'name', None),
            'variant_sku': getattr(getattr(item, 'variant', None), 'sku', None),
            'quantity': int(item.quantity),
            'unit_price': float(item.price or 0),
            'subtotal': float(item.total or 0),
        }
        for item in (order.items or [])
    ]
    return summary


@router.get('')
async def admin_list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_q: Optional[str] = Query(None, alias='status'),
    payment_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [Order.deleted_at.is_(None)]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append(
            or_(
                Order.tracking_code.ilike(q),
                Order.receiver_phone.ilike(q),
                Order.pancake_order_id.ilike(q),
            )
        )

    if status_q and status_q.strip():
        filters.append(func.lower(func.cast(Order.status, String)) == status_q.strip().lower())

    if payment_status and payment_status.strip():
        filters.append(func.lower(Order.payment_status) == payment_status.strip().lower())

    count_stmt = select(func.count(Order.id))
    if filters:
        count_stmt = count_stmt.where(and_(*filters))
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    if filters:
        stmt = stmt.where(and_(*filters))

    rows = (await db.execute(stmt)).scalars().all()
    data = [_to_order_summary(order) for order in rows]

    return {
        'data': data,
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'total_pages': (total + limit - 1) // limit if total > 0 else 0,
        },
    }


@router.get('/{order_id}')
async def admin_get_order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.items).selectinload(OrderItem.variant),
        )
        .where(Order.id == order_id, Order.deleted_at.is_(None))
        .limit(1)
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail='Order not found')

    return {'data': _to_order_detail(order)}


@router.patch('/bulk')
async def admin_bulk_orders(
    body: AdminBulkOrdersBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = str(body.action or '').strip().lower()
    if action not in ('status', 'soft_delete'):
        raise HTTPException(status_code=400, detail='Invalid bulk action')

    updated = 0
    failed: list[dict] = []

    stmt = select(Order).where(Order.id.in_(body.ids), Order.deleted_at.is_(None))
    orders = (await db.execute(stmt)).scalars().all()
    by_id = {int(o.id): o for o in orders}

    now = datetime.utcnow()
    sync_errors: list[dict] = []
    for oid in body.ids:
        order = by_id.get(int(oid))
        if not order:
            failed.append({'id': oid, 'reason': 'NOT_FOUND'})
            continue

        if action == 'status':
            next_status_raw = str(body.status or '').strip().lower()
            if not next_status_raw:
                failed.append({'id': oid, 'reason': 'INVALID_STATUS'})
                continue
            next_status = _coerce_order_status(next_status_raw)
            pancake_status_override = pancake_order_service.local_status_to_pancake_status(next_status_raw)
            order.status = next_status
            order.updated_at = now

            resolved_pancake_order_id = _resolve_pancake_order_id(order)
            if resolved_pancake_order_id and pancake_order_service.is_enabled():
                try:
                    result = await pancake_order_service.update_order_status(
                        pancake_order_id=resolved_pancake_order_id,
                        local_status=next_status,
                        pancake_status=pancake_status_override,
                    )
                    order.pancake_payload = result
                except PancakeOrderSyncError as exc:
                    if pancake_order_service.is_not_found_sync_error(exc):
                        _mark_order_detached_from_pancake(order, reason='REMOTE_ORDER_NOT_FOUND')
                        sync_errors.append({'id': oid, 'reason': 'REMOTE_ORDER_NOT_FOUND_DETACHED'})
                        updated += 1
                        continue
                    sync_errors.append({'id': oid, 'reason': str(exc)})
                    if settings.PANCAKE_ORDER_STATUS_SYNC_STRICT or settings.PANCAKE_SYNC_STRICT:
                        await db.rollback()
                        raise HTTPException(status_code=502, detail=f'Failed to sync order status to Pancake: {exc}')
            elif order.pancake_order_id:
                _mark_order_detached_from_pancake(order, reason='INVALID_PANCAKE_ORDER_ID_MAPPING')
                sync_errors.append({'id': oid, 'reason': 'INVALID_PANCAKE_ORDER_ID_MAPPING_DETACHED'})
            updated += 1
            continue

        if action == 'soft_delete':
            order.deleted_at = now
            order.updated_at = now
            if _normalize_status(order.status) != 'cancelled':
                order.status = 'cancelled'

            resolved_pancake_order_id = _resolve_pancake_order_id(order)
            if resolved_pancake_order_id and pancake_order_service.is_enabled():
                try:
                    result = await pancake_order_service.update_order_status(
                        pancake_order_id=resolved_pancake_order_id,
                        local_status='cancelled',
                    )
                    order.pancake_payload = result
                except PancakeOrderSyncError as exc:
                    if pancake_order_service.is_not_found_sync_error(exc):
                        _mark_order_detached_from_pancake(order, reason='REMOTE_ORDER_NOT_FOUND')
                        sync_errors.append({'id': oid, 'reason': 'REMOTE_ORDER_NOT_FOUND_DETACHED'})
                        updated += 1
                        continue
                    sync_errors.append({'id': oid, 'reason': str(exc)})
                    if settings.PANCAKE_ORDER_STATUS_SYNC_STRICT or settings.PANCAKE_SYNC_STRICT:
                        await db.rollback()
                        raise HTTPException(status_code=502, detail=f'Failed to sync order status to Pancake: {exc}')
            elif order.pancake_order_id:
                _mark_order_detached_from_pancake(order, reason='INVALID_PANCAKE_ORDER_ID_MAPPING')
                sync_errors.append({'id': oid, 'reason': 'INVALID_PANCAKE_ORDER_ID_MAPPING_DETACHED'})
            updated += 1

    await db.commit()
    return {'success': True, 'updated': updated, 'failed': failed, 'sync_failed': sync_errors}


@router.patch('/{order_id}')
async def admin_update_order(
    order_id: int,
    body: AdminOrderUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail='Order not found')

    payload = body.model_dump(exclude_unset=True, by_alias=False)

    status_raw_input: Optional[str] = None

    if 'status' in payload and payload['status'] is not None:
        status_raw_input = str(payload['status']).strip().lower()
        order.status = _coerce_order_status(status_raw_input)
    if 'note' in payload:
        order.note = payload['note']
    if 'tracking_code' in payload and payload['tracking_code'] is not None:
        order.tracking_code = str(payload['tracking_code']).strip() or None

    status_changed = 'status' in payload and payload['status'] is not None
    resolved_pancake_order_id = _resolve_pancake_order_id(order)
    if status_changed and resolved_pancake_order_id and pancake_order_service.is_enabled():
        try:
            pancake_status_override = pancake_order_service.local_status_to_pancake_status(status_raw_input or _normalize_status(order.status))
            result = await pancake_order_service.update_order_status(
                pancake_order_id=resolved_pancake_order_id,
                local_status=_normalize_status(order.status),
                pancake_status=pancake_status_override,
            )
            order.pancake_payload = result
        except PancakeOrderSyncError as exc:
            if pancake_order_service.is_not_found_sync_error(exc):
                _mark_order_detached_from_pancake(order, reason='REMOTE_ORDER_NOT_FOUND')
                await db.commit()
                await db.refresh(order)
                stmt = (
                    select(Order)
                    .options(
                        selectinload(Order.items).selectinload(OrderItem.product),
                        selectinload(Order.items).selectinload(OrderItem.variant),
                    )
                    .where(Order.id == order.id)
                    .limit(1)
                )
                updated = (await db.execute(stmt)).scalar_one()
                return {'data': _to_order_detail(updated), 'sync_warning': 'REMOTE_ORDER_NOT_FOUND_DETACHED'}
            logger.exception('Failed to sync order status to Pancake (order_id=%s)', order.id)
            if settings.PANCAKE_ORDER_STATUS_SYNC_STRICT or settings.PANCAKE_SYNC_STRICT:
                await db.rollback()
                raise HTTPException(status_code=502, detail=f'Failed to sync order status to Pancake: {exc}')
    elif status_changed and order.pancake_order_id:
        _mark_order_detached_from_pancake(order, reason='INVALID_PANCAKE_ORDER_ID_MAPPING')

    await db.commit()
    await db.refresh(order)

    stmt = (
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.items).selectinload(OrderItem.variant),
        )
        .where(Order.id == order.id)
        .limit(1)
    )
    updated = (await db.execute(stmt)).scalar_one()

    return {'data': _to_order_detail(updated)}


@router.delete('/{order_id}')
async def admin_soft_delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail='Order not found')

    now = datetime.utcnow()
    order.deleted_at = now
    order.updated_at = now
    if _normalize_status(order.status) != 'cancelled':
        order.status = 'cancelled'

    resolved_pancake_order_id = _resolve_pancake_order_id(order)
    if resolved_pancake_order_id and pancake_order_service.is_enabled():
        try:
            result = await pancake_order_service.update_order_status(
                pancake_order_id=resolved_pancake_order_id,
                local_status='cancelled',
            )
            order.pancake_payload = result
        except PancakeOrderSyncError as exc:
            if pancake_order_service.is_not_found_sync_error(exc):
                _mark_order_detached_from_pancake(order, reason='REMOTE_ORDER_NOT_FOUND')
                await db.commit()
                return {'success': True, 'sync_warning': 'REMOTE_ORDER_NOT_FOUND_DETACHED'}
            logger.exception('Failed to sync soft-delete status to Pancake (order_id=%s)', order.id)
            if settings.PANCAKE_ORDER_STATUS_SYNC_STRICT or settings.PANCAKE_SYNC_STRICT:
                await db.rollback()
                raise HTTPException(status_code=502, detail=f'Failed to sync order status to Pancake: {exc}')
    elif order.pancake_order_id:
        _mark_order_detached_from_pancake(order, reason='INVALID_PANCAKE_ORDER_ID_MAPPING')

    await db.commit()
    return {'success': True}
