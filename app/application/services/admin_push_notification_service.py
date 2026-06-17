from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.domain.models.admin_notification import AdminNotification
from app.domain.models.admin_push_subscription import AdminPushSubscription


def is_web_push_configured() -> bool:
    return bool(
        str(settings.WEB_PUSH_VAPID_PUBLIC_KEY or "").strip()
        and str(settings.WEB_PUSH_VAPID_PRIVATE_KEY or "").strip()
    )


def get_web_push_public_key() -> str | None:
    key = str(settings.WEB_PUSH_VAPID_PUBLIC_KEY or "").strip()
    return key or None


async def upsert_admin_push_subscription(
    *,
    user_id: int | None,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> AdminPushSubscription:
    now = datetime.utcnow()
    async with async_session() as db:
        stmt = select(AdminPushSubscription).where(AdminPushSubscription.endpoint == endpoint).limit(1)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            existing = AdminPushSubscription(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=(user_agent or "")[:500] or None,
                is_active=True,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            db.add(existing)
        else:
            existing.user_id = user_id or existing.user_id
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = (user_agent or "")[:500] or existing.user_agent
            existing.is_active = True
            existing.updated_at = now
            existing.last_seen_at = now

        await db.commit()
        await db.refresh(existing)
        return existing


async def deactivate_admin_push_subscription(endpoint: str) -> bool:
    async with async_session() as db:
        stmt = select(AdminPushSubscription).where(AdminPushSubscription.endpoint == endpoint).limit(1)
        subscription = (await db.execute(stmt)).scalar_one_or_none()
        if subscription is None:
            return False
        subscription.is_active = False
        subscription.updated_at = datetime.utcnow()
        await db.commit()
        return True


def _build_subscription_info(subscription: AdminPushSubscription) -> dict[str, Any]:
    return {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }


def _send_web_push(subscription_info: dict[str, Any], payload: dict[str, Any]) -> None:
    from pywebpush import webpush

    webpush(
        subscription_info=subscription_info,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=str(settings.WEB_PUSH_VAPID_PRIVATE_KEY or "").strip(),
        vapid_claims={"sub": str(settings.WEB_PUSH_VAPID_SUBJECT or "mailto:admin@locsang.vn")},
    )


def _build_order_item_summary(product_names: list[str] | None) -> str:
    names = [str(name or "").strip() for name in (product_names or []) if str(name or "").strip()]
    if not names:
        return "sản phẩm"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} và {len(names) - 1} sản phẩm khác"


async def _mark_subscription_inactive(subscription_id: int) -> None:
    async with async_session() as db:
        subscription = await db.get(AdminPushSubscription, subscription_id)
        if subscription is None:
            return
        subscription.is_active = False
        subscription.updated_at = datetime.utcnow()
        await db.commit()


async def send_new_order_push_notifications(
    *,
    order_id: int,
    tracking_code: str | None,
    receiver_name: str | None,
    total_amount: float | int | None,
    product_names: list[str] | None = None,
) -> None:
    if not is_web_push_configured():
        return

    amount = int(float(total_amount or 0))
    item_summary = _build_order_item_summary(product_names)
    payload = {
        "title": "Có đơn hàng mới",
        "body": f"{receiver_name or 'Khách hàng'} vừa đặt {item_summary} - {amount:,}đ".replace(",", "."),
        "url": f"/admin/orders?orderId={order_id}",
        "tag": f"locsang-order-{order_id}",
        "orderId": order_id,
        "trackingCode": tracking_code,
    }

    async with async_session() as db:
        stmt = select(AdminPushSubscription).where(AdminPushSubscription.is_active.is_(True))
        subscriptions = (await db.execute(stmt)).scalars().all()

    for subscription in subscriptions:
        subscription_info = _build_subscription_info(subscription)
        try:
            await asyncio.to_thread(_send_web_push, subscription_info, payload)
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                await _mark_subscription_inactive(int(subscription.id))


async def create_new_order_admin_notification(
    *,
    order_id: int,
    tracking_code: str | None,
    receiver_name: str | None,
    total_amount: float | int | None,
    product_names: list[str] | None = None,
) -> None:
    amount = int(float(total_amount or 0))
    item_summary = _build_order_item_summary(product_names)
    title = "Có đơn hàng mới"
    body = f"{receiver_name or 'Khách hàng'} vừa đặt {item_summary} - {amount:,}đ".replace(",", ".")
    url = f"/admin/orders?orderId={order_id}"

    async with async_session() as db:
        notification = AdminNotification(
            type="order",
            title=title,
            body=body,
            url=url,
            order_id=order_id,
            tracking_code=tracking_code,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(notification)
        await db.commit()

    await send_new_order_push_notifications(
        order_id=order_id,
        tracking_code=tracking_code,
        receiver_name=receiver_name,
        total_amount=total_amount,
        product_names=product_names,
    )
