import hashlib
import secrets
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.core.role_helpers import get_or_create_customer_role_id, is_customer_role
from app.core.security import create_access_token, get_password_hash, verify_password
from app.domain.models.account_cart_item import AccountCartItem
from app.domain.models.order import Order, OrderStatus
from app.domain.models.user import User
from app.presentation.api.public_api.deps import get_current_account_user
from app.services.email_service import send_password_changed_email, send_password_reset_email


router = APIRouter(prefix="/account", tags=["Public Account"])
STOREFRONT_TOKEN_SCOPE = "storefront"
PASSWORD_RESET_TOKEN_SCOPE = "storefront_password_reset"


class AccountRegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class AccountLoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AccountForgotPasswordBody(BaseModel):
    email: EmailStr


class AccountResetPasswordBody(BaseModel):
    token: str = Field(min_length=32)
    new_password: str = Field(min_length=8, max_length=128)


class AccountFacebookLoginBody(BaseModel):
    access_token: str = Field(min_length=20, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


class AccountUpdateBody(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class AccountProfileResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    avatar_url: Optional[str] = None
    created_at: str
    updated_at: str


class AccountAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AccountProfileResponse


class AccountMessageResponse(BaseModel):
    success: bool = True
    message: str


class AccountForgotPasswordResponse(AccountMessageResponse):
    reset_token: Optional[str] = None
    reset_url: Optional[str] = None


class AccountOrderItemResponse(BaseModel):
    product_id: int
    product_variant_id: Optional[int] = None
    name: str
    sku: Optional[str] = None
    quantity: int
    unit_price: float
    subtotal: float


class AccountOrderResponse(BaseModel):
    id: int
    tracking_code: Optional[str] = None
    status: str
    payment_status: str
    payment_method: str
    receiver_name: Optional[str] = None
    receiver_phone: Optional[str] = None
    receiver_address: Optional[str] = None
    total_amount: float
    created_at: str
    items: list[AccountOrderItemResponse]


class AccountOrdersResponse(BaseModel):
    success: bool = True
    data: list[AccountOrderResponse]


class AccountOrderActionResponse(BaseModel):
    success: bool = True
    data: AccountOrderResponse


class AccountCartItemBody(BaseModel):
    item_key: Optional[str] = Field(default=None, max_length=120)
    product_id: Optional[int] = None
    product_variant_id: Optional[int] = None
    sku: Optional[str] = Field(default=None, max_length=120)
    variant_label: Optional[str] = Field(default=None, max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)
    image: Optional[str] = Field(default="", max_length=1000)
    price: float = 0
    quantity: int = Field(default=1, ge=1)


class AccountCartBody(BaseModel):
    items: list[AccountCartItemBody] = Field(default_factory=list)


class AccountCartItemResponse(BaseModel):
    item_key: str
    product_id: Optional[int] = None
    product_variant_id: Optional[int] = None
    sku: Optional[str] = None
    variant_label: Optional[str] = None
    title: str
    image: str
    price: float
    quantity: int


class AccountCartResponse(BaseModel):
    success: bool = True
    data: list[AccountCartItemResponse]


def _to_profile(user: User) -> AccountProfileResponse:
    explicit_avatar = str(getattr(user, "avatar_url", "") or "").strip()
    normalized_email = str(user.email or "").strip().lower()
    avatar_hash = hashlib.md5(normalized_email.encode("utf-8")).hexdigest()
    fallback_avatar = f"https://www.gravatar.com/avatar/{avatar_hash}?d=identicon&s=128"

    return AccountProfileResponse(
        id=int(user.id),
        email=str(user.email),
        full_name=str(user.full_name),
        avatar_url=explicit_avatar or fallback_avatar,
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
    )


async def _get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    stmt = select(User).where(func.lower(User.email) == str(email).strip().lower())
    return (await db.execute(stmt)).scalars().first()


def _create_password_reset_token(user: User) -> str:
    expires = timedelta(minutes=max(5, int(settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES or 30)))
    return create_access_token(
        data={
            "sub": str(user.id),
            "scope": PASSWORD_RESET_TOKEN_SCOPE,
            "email": str(user.email),
        },
        expires_delta=expires,
    )


def _decode_password_reset_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    if str(payload.get("scope") or "") != PASSWORD_RESET_TOKEN_SCOPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token scope")
    if not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token payload")

    return payload


def _extract_social_picture_url(payload: dict) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    direct = str(payload.get("picture_url") or payload.get("picture") or "").strip()
    if direct.startswith("http://") or direct.startswith("https://"):
        return direct

    picture_obj = payload.get("picture")
    if isinstance(picture_obj, dict):
        nested = picture_obj.get("data")
        if isinstance(nested, dict):
            nested_url = str(nested.get("url") or "").strip()
            if nested_url.startswith("http://") or nested_url.startswith("https://"):
                return nested_url

    return None


async def _verify_facebook_access_token(access_token: str) -> dict:
    token = str(access_token or "").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Facebook credential")

    app_id = str(settings.FACEBOOK_APP_ID or "").strip()
    app_secret = str(settings.FACEBOOK_APP_SECRET or "").strip()

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            if app_id and app_secret:
                debug_response = await client.get(
                    "https://graph.facebook.com/debug_token",
                    params={
                        "input_token": token,
                        "access_token": f"{app_id}|{app_secret}",
                    },
                )
                if debug_response.status_code != 200:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Facebook credential")

                debug_payload = debug_response.json() if isinstance(debug_response.json(), dict) else {}
                debug_data = debug_payload.get("data") if isinstance(debug_payload.get("data"), dict) else {}
                if not bool(debug_data.get("is_valid")):
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Facebook credential")

                token_app_id = str(debug_data.get("app_id") or "").strip()
                if app_id and token_app_id and token_app_id != app_id:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Facebook app mismatch")

            profile_response = await client.get(
                "https://graph.facebook.com/me",
                params={
                    "fields": "id,name,email,picture.type(large)",
                    "access_token": token,
                },
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach Facebook token service")

    if profile_response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Facebook credential")

    payload = profile_response.json() if isinstance(profile_response.json(), dict) else {}
    return payload


@router.post("/register", response_model=AccountAuthResponse, status_code=status.HTTP_201_CREATED)
async def register_account(
    body: AccountRegisterBody,
    _limited: None = Depends(rate_limit("storefront-register", limit=8, window_seconds=300)),
    db: AsyncSession = Depends(get_db),
):
    existing = await _get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    role_id = await get_or_create_customer_role_id(db)
    user = User(
        email=str(body.email).strip().lower(),
        hashed_password=get_password_hash(body.password),
        full_name=str(body.full_name).strip(),
        is_active=True,
        role_id=role_id,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(
        data={"sub": str(user.id), "scope": STOREFRONT_TOKEN_SCOPE},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return AccountAuthResponse(access_token=access_token, token_type="bearer", user=_to_profile(user))


@router.post("/login", response_model=AccountAuthResponse)
async def login_account(
    body: AccountLoginBody,
    _limited: None = Depends(rate_limit("storefront-login", limit=12, window_seconds=60)),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    role_id = getattr(user, "role_id", None)
    if not await is_customer_role(db, role_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not allowed to use storefront login",
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "scope": STOREFRONT_TOKEN_SCOPE},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return AccountAuthResponse(access_token=access_token, token_type="bearer", user=_to_profile(user))


@router.post("/facebook", response_model=AccountAuthResponse)
async def login_account_facebook(
    body: AccountFacebookLoginBody,
    _limited: None = Depends(rate_limit("storefront-facebook-login", limit=12, window_seconds=60)),
    db: AsyncSession = Depends(get_db),
):
    facebook_payload = await _verify_facebook_access_token(body.access_token)

    facebook_user_id = str(facebook_payload.get("id") or "").strip()
    if not facebook_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Facebook profile")

    requested_user_id = str(body.user_id or "").strip()
    if requested_user_id and requested_user_id != facebook_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Facebook user mismatch")

    email = str(facebook_payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Facebook account does not expose email. Please allow email permission.",
        )

    facebook_avatar = _extract_social_picture_url(facebook_payload)
    user = await _get_user_by_email(db, email)
    if user is None:
        role_id = await get_or_create_customer_role_id(db)
        full_name = str(facebook_payload.get("name") or email.split("@")[0] or "Khach hang").strip()
        user = User(
            email=email,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            full_name=full_name,
            avatar_url=facebook_avatar,
            is_active=True,
            role_id=role_id,
        )
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
    elif facebook_avatar and str(getattr(user, "avatar_url", "") or "").strip() != facebook_avatar:
        user.avatar_url = facebook_avatar
        await db.flush()
        await db.commit()
        await db.refresh(user)

    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    if not await is_customer_role(db, getattr(user, "role_id", None)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not allowed to use storefront login",
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "scope": STOREFRONT_TOKEN_SCOPE},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return AccountAuthResponse(access_token=access_token, token_type="bearer", user=_to_profile(user))


@router.post("/forgot-password", response_model=AccountForgotPasswordResponse)
async def forgot_account_password(
    body: AccountForgotPasswordBody,
    background_tasks: BackgroundTasks,
    _limited: None = Depends(rate_limit("storefront-forgot-password", limit=5, window_seconds=300)),
    db: AsyncSession = Depends(get_db),
):
    generic = AccountForgotPasswordResponse(message="Neu email ton tai, ban se nhan duoc huong dan dat lai mat khau.")

    user = await _get_user_by_email(db, body.email)
    if user is None:
        return generic

    if not await is_customer_role(db, getattr(user, "role_id", None)):
        return generic

    reset_token = _create_password_reset_token(user)
    reset_url = f"{str(settings.FRONTEND_BASE_URL).rstrip('/')}/account/login?mode=reset&token={reset_token}"
    expires_minutes = max(5, int(settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES or 30))

    background_tasks.add_task(
        send_password_reset_email,
        recipient_email=str(user.email),
        reset_url=reset_url,
        expires_minutes=expires_minutes,
    )

    if bool(settings.AUTH_DEBUG_EXPOSE_PASSWORD_RESET_TOKEN):
        generic.reset_token = reset_token
        generic.reset_url = reset_url

    return generic


@router.post("/reset-password", response_model=AccountMessageResponse)
async def reset_account_password(
    body: AccountResetPasswordBody,
    background_tasks: BackgroundTasks,
    _limited: None = Depends(rate_limit("storefront-reset-password", limit=8, window_seconds=300)),
    db: AsyncSession = Depends(get_db),
):
    payload = _decode_password_reset_token(body.token)
    user_id = int(payload.get("sub"))

    stmt = select(User).where(User.id == user_id)
    user = (await db.execute(stmt)).scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not await is_customer_role(db, getattr(user, "role_id", None)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid account role")

    token_email = str(payload.get("email") or "").strip().lower()
    if token_email and token_email != str(user.email).strip().lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token does not match account")

    user.hashed_password = get_password_hash(str(body.new_password))
    await db.flush()
    await db.commit()

    background_tasks.add_task(
        send_password_changed_email,
        recipient_email=str(user.email),
    )

    return AccountMessageResponse(message="Dat lai mat khau thanh cong")


@router.get("/me", response_model=AccountProfileResponse)
async def read_account_me(current_user: User = Depends(get_current_account_user)):
    return _to_profile(current_user)


@router.put("/me", response_model=AccountProfileResponse)
async def update_account_me(
    body: AccountUpdateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    update_data = body.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"] is not None:
        normalized_email = str(update_data["email"]).strip().lower()
        if normalized_email != str(current_user.email).lower():
            existing = await _get_user_by_email(db, normalized_email)
            if existing and int(existing.id) != int(current_user.id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
            current_user.email = normalized_email

    if "full_name" in update_data and update_data["full_name"] is not None:
        current_user.full_name = str(update_data["full_name"]).strip()

    if "password" in update_data and update_data["password"]:
        current_user.hashed_password = get_password_hash(str(update_data["password"]))

    await db.flush()
    await db.commit()
    await db.refresh(current_user)
    return _to_profile(current_user)


def _order_status_text(value: object) -> str:
    raw = str(getattr(value, "value", value) or "pending").strip().lower()
    if raw in {"processed", "shipped", "delivered", "processing"}:
        return "processed"
    if raw == "cancelled":
        return "cancelled"
    return "pending"


def _order_to_response(order: Order) -> AccountOrderResponse:
    items: list[AccountOrderItemResponse] = []
    for item in order.items or []:
        product = getattr(item, "product", None)
        variant = getattr(item, "variant", None)
        product_name = str(getattr(product, "name", "") or f"Sản phẩm #{item.product_id}")
        variant_label = str(getattr(variant, "sku", "") or "").strip()
        if variant_label:
            product_name = f"{product_name} ({variant_label})"

        items.append(
            AccountOrderItemResponse(
                product_id=int(item.product_id),
                product_variant_id=int(item.product_variant_id) if item.product_variant_id is not None else None,
                name=product_name,
                sku=getattr(variant, "sku", None) or getattr(product, "sku", None),
                quantity=int(item.quantity),
                unit_price=float(item.price or 0),
                subtotal=float(item.total or 0),
            )
        )

    return AccountOrderResponse(
        id=int(order.id),
        tracking_code=order.tracking_code,
        status=_order_status_text(order.status),
        payment_status=str(order.payment_status or "pending"),
        payment_method=str(order.payment_method or "cod"),
        receiver_name=order.receiver_name,
        receiver_phone=order.receiver_phone,
        receiver_address=order.receiver_address,
        total_amount=float(order.total_amount or 0),
        created_at=order.created_at.isoformat() if order.created_at else "",
        items=items,
    )


@router.get("/orders", response_model=AccountOrdersResponse)
async def get_my_orders(
    receiver_phone: Optional[str] = Query(default=None, alias="receiverPhone"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    stmt = (
        select(Order)
        .where(
            Order.user_id == int(current_user.id),
            Order.deleted_at.is_(None),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(40)
    )
    orders = (await db.execute(stmt)).scalars().all()
    return AccountOrdersResponse(success=True, data=[_order_to_response(order) for order in orders])


@router.post("/orders/{order_id}/cancel", response_model=AccountOrderActionResponse)
async def cancel_my_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    stmt = (
        select(Order)
        .where(
            Order.id == int(order_id),
            Order.user_id == int(current_user.id),
            Order.deleted_at.is_(None),
        )
        .limit(1)
    )
    order = (await db.execute(stmt)).scalars().first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    current_status = _order_status_text(order.status)

    if current_status == "processed":
        raise HTTPException(status_code=409, detail="Đơn hàng đã xử lý và không thể hủy")

    if current_status == "cancelled":
        return AccountOrderActionResponse(success=True, data=_order_to_response(order))

    order.status = OrderStatus.CANCELLED.value
    await db.flush()
    await db.commit()

    return AccountOrderActionResponse(success=True, data=_order_to_response(order))


@router.get("/cart", response_model=AccountCartResponse)
async def get_my_cart(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    stmt = (
        select(AccountCartItem)
        .where(AccountCartItem.user_id == int(current_user.id))
        .order_by(AccountCartItem.position.asc(), AccountCartItem.id.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return AccountCartResponse(success=True, data=[_cart_row_to_response(row) for row in rows])


@router.put("/cart", response_model=AccountCartResponse)
async def replace_my_cart(
    body: AccountCartBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    merged: dict[str, AccountCartItemBody] = {}
    order: list[str] = []

    for raw_item in body.items or []:
        item = _normalize_cart_item(raw_item)
        if not item.item_key:
            continue
        if item.item_key in merged:
            existing = merged[item.item_key]
            existing.quantity = max(1, int(existing.quantity)) + max(1, int(item.quantity))
            continue
        merged[item.item_key] = item
        order.append(item.item_key)

    await db.execute(delete(AccountCartItem).where(AccountCartItem.user_id == int(current_user.id)))

    rows: list[AccountCartItem] = []
    for idx, key in enumerate(order):
        item = merged[key]
        rows.append(
            AccountCartItem(
                user_id=int(current_user.id),
                item_key=item.item_key,
                product_id=item.product_id,
                product_variant_id=item.product_variant_id,
                sku=item.sku,
                variant_label=item.variant_label,
                title=item.title,
                image=item.image,
                price=float(item.price or 0),
                quantity=max(1, int(item.quantity or 1)),
                position=idx,
            )
        )

    if rows:
        db.add_all(rows)

    await db.flush()
    await db.commit()

    return AccountCartResponse(success=True, data=[_cart_row_to_response(row) for row in rows])


def _normalize_cart_item(item: AccountCartItemBody) -> AccountCartItemBody:
    normalized_product_id = int(item.product_id) if item.product_id is not None else None
    normalized_variant_id = int(item.product_variant_id) if item.product_variant_id is not None else None
    normalized_sku = str(item.sku).strip() if item.sku else None
    normalized_variant_label = str(item.variant_label).strip() if item.variant_label else None
    normalized_title = str(item.title).strip() if item.title else ""
    normalized_item_key = str(item.item_key).strip() if item.item_key else ""

    if not normalized_item_key:
        if normalized_product_id is not None:
            variant_part = str(normalized_variant_id if normalized_variant_id is not None else 0)
            normalized_item_key = f"p:{normalized_product_id}:v:{variant_part}"
        elif normalized_sku:
            normalized_item_key = f"sku:{normalized_sku}"
        elif normalized_title:
            normalized_item_key = f"custom:{normalized_title.lower()}"

    if not normalized_title:
        normalized_title = "Product"

    return AccountCartItemBody(
        item_key=normalized_item_key,
        product_id=normalized_product_id,
        product_variant_id=normalized_variant_id,
        sku=normalized_sku,
        variant_label=normalized_variant_label,
        title=normalized_title,
        image=str(item.image or "").strip(),
        price=float(item.price or 0),
        quantity=max(1, int(item.quantity or 1)),
    )


def _cart_row_to_response(row: AccountCartItem) -> AccountCartItemResponse:
    return AccountCartItemResponse(
        item_key=str(row.item_key),
        product_id=int(row.product_id) if row.product_id is not None else None,
        product_variant_id=int(row.product_variant_id) if row.product_variant_id is not None else None,
        sku=str(row.sku) if row.sku else None,
        variant_label=str(row.variant_label) if row.variant_label else None,
        title=str(row.title),
        image=str(row.image or ""),
        price=float(row.price or 0),
        quantity=max(1, int(row.quantity or 1)),
    )
