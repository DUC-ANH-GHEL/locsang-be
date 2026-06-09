from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.application.services.admin_push_notification_service import (
    deactivate_admin_push_subscription,
    get_web_push_public_key,
    is_web_push_configured,
    upsert_admin_push_subscription,
)
from app.core.deps import get_current_user
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
