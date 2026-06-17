from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.admin_push_notification_service import (
    deactivate_admin_push_subscription,
    get_web_push_public_key,
    is_web_push_configured,
    upsert_admin_push_subscription,
)
from app.core.deps import get_current_user
from app.core.database import get_db
from app.domain.models.admin_notification import AdminNotification
from app.domain.models.user import User


router = APIRouter(prefix="/notifications", tags=["admin-notifications"])


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(..., min_length=1)
    auth: str = Field(..., min_length=1)


class PushSubscriptionBody(BaseModel):
    endpoint: str = Field(..., min_length=10)
    keys: PushSubscriptionKeys


class PushUnsubscribeBody(BaseModel):
    endpoint: str = Field(..., min_length=10)


def _notification_to_response(notification: AdminNotification) -> dict:
    return {
        "id": int(notification.id),
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "url": notification.url,
        "order_id": notification.order_id,
        "tracking_code": notification.tracking_code,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


def _notification_ordering():
    unread_first = case((AdminNotification.read_at.is_(None), 0), else_=1)
    return (
        unread_first.asc(),
        AdminNotification.created_at.desc(),
        AdminNotification.id.desc(),
    )


@router.get("")
async def list_admin_notifications(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_limit = min(50, max(1, int(limit or 20)))
    stmt = (
        select(AdminNotification)
        .order_by(*_notification_ordering())
        .limit(safe_limit)
    )
    notifications = (await db.execute(stmt)).scalars().all()
    unread_count = int((await db.execute(select(func.count(AdminNotification.id)).where(AdminNotification.read_at.is_(None)))).scalar_one())
    return {
        "data": [_notification_to_response(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@router.patch("/{notification_id}/read")
async def mark_admin_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await db.get(AdminNotification, notification_id)
    if notification is None:
        return {"success": True, "updated": False}

    if notification.read_at is None:
        from datetime import datetime

        notification.read_at = datetime.utcnow()
        notification.updated_at = notification.read_at
        await db.commit()

    return {"success": True, "updated": True}


@router.patch("/read-all")
async def mark_all_admin_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime

    now = datetime.utcnow()
    stmt = select(AdminNotification).where(AdminNotification.read_at.is_(None))
    notifications = (await db.execute(stmt)).scalars().all()
    for notification in notifications:
        notification.read_at = now
        notification.updated_at = now
    await db.commit()
    return {"success": True, "updated": len(notifications)}


@router.get("/push/config")
async def get_push_config(current_user: User = Depends(get_current_user)):
    return {
        "configured": is_web_push_configured(),
        "publicKey": get_web_push_public_key(),
    }


@router.post("/push/subscriptions")
async def save_push_subscription(
    body: PushSubscriptionBody,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    subscription = await upsert_admin_push_subscription(
        user_id=int(current_user.id),
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=request.headers.get("user-agent"),
    )
    return {"success": True, "id": int(subscription.id)}


@router.delete("/push/subscriptions")
async def delete_push_subscription(
    body: PushUnsubscribeBody,
    current_user: User = Depends(get_current_user),
):
    removed = await deactivate_admin_push_subscription(body.endpoint)
    return {"success": True, "removed": removed}
