from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.admin_order import AdminBulkOrdersBody, AdminOrderUpdateBody
from app.core.deps import get_current_user, get_db
from app.domain.models.admin_notification import AdminNotification
from app.domain.models.order import Order, OrderStatus
from app.domain.models.order_item import OrderItem
from app.domain.models.user import User


router = APIRouter()
ORDER_STATUS_NEW = "pending"
ORDER_STATUS_PROCESSED = "processed"
ORDER_STATUS_CANCELLED = "cancelled"
LOCAL_ORDER_STATUSES = {ORDER_STATUS_NEW, ORDER_STATUS_PROCESSED, ORDER_STATUS_CANCELLED}
LEGACY_PROCESSED_STATUSES = {"processing", "shipped", "delivered"}


def _normalize_status(value: object) -> str:
    if value is None:
        return ORDER_STATUS_NEW
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().lower()
    if normalized in LEGACY_PROCESSED_STATUSES:
        return ORDER_STATUS_PROCESSED
    return normalized if normalized in LOCAL_ORDER_STATUSES else ORDER_STATUS_NEW


def _coerce_order_status(value: object) -> str:
    normalized = _normalize_status(value)
    if normalized not in LOCAL_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid order status")
    return normalized


def _to_order_summary(order: Order) -> dict:
    items = list(order.items or [])
    first_item = items[0] if items else None
    first_product_name = None
    if first_item and getattr(first_item, "product", None) is not None:
        first_product_name = first_item.product.name

    return {
        "id": int(order.id),
        "tracking_code": order.tracking_code,
        "receiver_name": order.receiver_name,
        "receiver_phone": order.receiver_phone,
        "receiver_address": order.receiver_address,
        "status": _normalize_status(order.status),
        "payment_status": str(order.payment_status or "pending").lower(),
        "payment_method": str(order.payment_method or "cod").lower(),
        "total_amount": float(order.total_amount or 0),
        "item_count": len(items),
        "first_product_name": first_product_name,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _to_order_detail(order: Order) -> dict:
    summary = _to_order_summary(order)
    summary["items"] = [
        {
            "id": int(item.id),
            "product_id": int(item.product_id),
            "product_variant_id": int(item.product_variant_id) if item.product_variant_id is not None else None,
            "product_name": getattr(getattr(item, "product", None), "name", None),
            "variant_sku": getattr(getattr(item, "variant", None), "sku", None),
            "quantity": int(item.quantity),
            "unit_price": float(item.price or 0),
            "subtotal": float(item.total or 0),
        }
        for item in (order.items or [])
    ]
    return summary


async def _mark_order_notifications_read(db: AsyncSession, order_ids: object) -> int:
    if isinstance(order_ids, (str, int)):
        raw_ids = [order_ids]
    else:
        raw_ids = list(order_ids or [])

    safe_ids_set: set[int] = set()
    for raw_id in raw_ids:
        try:
            order_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if order_id > 0:
            safe_ids_set.add(order_id)
    safe_ids = sorted(safe_ids_set)
    if not safe_ids:
        return 0

    stmt = select(AdminNotification).where(
        AdminNotification.order_id.in_(safe_ids),
        AdminNotification.read_at.is_(None),
    )
    notifications = (await db.execute(stmt)).scalars().all()
    if not notifications:
        return 0

    now = datetime.utcnow()
    for notification in notifications:
        notification.read_at = now
        notification.updated_at = now
    return len(notifications)


@router.get("")
async def admin_list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_q: Optional[str] = Query(None, alias="status"),
    payment_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [Order.deleted_at.is_(None)]

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append(or_(Order.tracking_code.ilike(q), Order.receiver_phone.ilike(q)))

    if status_q and status_q.strip():
        normalized_status = _coerce_order_status(status_q)
        if normalized_status == ORDER_STATUS_PROCESSED:
            filters.append(func.lower(func.cast(Order.status, String)).in_([ORDER_STATUS_PROCESSED, *LEGACY_PROCESSED_STATUSES]))
        else:
            filters.append(func.lower(func.cast(Order.status, String)) == normalized_status)

    if payment_status and payment_status.strip():
        filters.append(func.lower(Order.payment_status) == payment_status.strip().lower())

    count_stmt = select(func.count(Order.id)).where(and_(*filters))
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .where(and_(*filters))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "data": [_to_order_summary(order) for order in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    }


@router.get("/{order_id}")
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
        raise HTTPException(status_code=404, detail="Order not found")

    if await _mark_order_notifications_read(db, order_id):
        await db.commit()

    return {"data": _to_order_detail(order)}


@router.patch("/bulk")
async def admin_bulk_orders(
    body: AdminBulkOrdersBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = str(body.action or "").strip().lower()
    if action not in ("status", "soft_delete"):
        raise HTTPException(status_code=400, detail="Invalid bulk action")

    updated = 0
    failed: list[dict] = []
    now = datetime.utcnow()
    status_updated_order_ids: list[int] = []

    stmt = select(Order).where(Order.id.in_(body.ids), Order.deleted_at.is_(None))
    orders = (await db.execute(stmt)).scalars().all()
    by_id = {int(o.id): o for o in orders}

    for oid in body.ids:
        order = by_id.get(int(oid))
        if not order:
            failed.append({"id": oid, "reason": "NOT_FOUND"})
            continue

        if action == "status":
            next_status = _coerce_order_status(body.status)
            order.status = next_status
            order.updated_at = now
            status_updated_order_ids.append(int(order.id))
            updated += 1
            continue

        order.deleted_at = now
        order.updated_at = now
        if _normalize_status(order.status) != "cancelled":
            order.status = OrderStatus.CANCELLED.value
        updated += 1

    if status_updated_order_ids:
        await _mark_order_notifications_read(db, status_updated_order_ids)

    await db.commit()
    return {"success": True, "updated": updated, "failed": failed}


@router.patch("/{order_id}")
async def admin_update_order(
    order_id: int,
    body: AdminOrderUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")

    payload = body.model_dump(exclude_unset=True, by_alias=False)
    if "status" in payload and payload["status"] is not None:
        order.status = _coerce_order_status(payload["status"])
    if "note" in payload:
        order.note = payload["note"]
    if "tracking_code" in payload and payload["tracking_code"] is not None:
        order.tracking_code = str(payload["tracking_code"]).strip() or None
    order.updated_at = datetime.utcnow()
    await _mark_order_notifications_read(db, order.id)

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
    return {"data": _to_order_detail(updated)}


@router.delete("/{order_id}")
async def admin_soft_delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = await db.get(Order, order_id)
    if not order or order.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Order not found")

    now = datetime.utcnow()
    order.deleted_at = now
    order.updated_at = now
    if _normalize_status(order.status) != "cancelled":
        order.status = OrderStatus.CANCELLED.value

    await db.commit()
    return {"success": True}
