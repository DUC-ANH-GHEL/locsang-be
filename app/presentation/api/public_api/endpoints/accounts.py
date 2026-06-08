import asyncio
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

from app.application.services.pancake_order_service import PancakeOrderService
from app.core.config import settings
from app.core.database import get_db
from app.core.role_helpers import get_or_create_customer_role_id, is_customer_role
from app.core.security import create_access_token, get_password_hash, verify_password
from app.domain.models.account_cart_item import AccountCartItem
from app.domain.models.order import Order, OrderStatus
from app.domain.models.user import User
from app.presentation.api.public_api.deps import get_current_account_user
from app.services.email_service import send_password_changed_email, send_password_reset_email


router = APIRouter(prefix="/account", tags=["Public Account"])
pancake_order_service = PancakeOrderService()
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


class AccountGoogleLoginBody(BaseModel):
    id_token: str = Field(min_length=20)
    client_id: Optional[str] = Field(default=None, max_length=255)


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
    pancake_order_id: Optional[str] = None
    status: str
    pancake_status_raw: Optional[object] = None
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


class AccountOrderRepairSummaryResponse(BaseModel):
    success: bool = True
    repaired: int
    scanned: int


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


async def _verify_google_id_token(id_token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": id_token},
            )
    except Exception:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach Google token service")

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credential")

    payload = response.json() if isinstance(response.json(), dict) else {}
    issuer = str(payload.get("iss") or "")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google issuer")

    email_verified = str(payload.get("email_verified") or "").lower()
    if email_verified not in {"true", "1"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

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
async def register_account(body: AccountRegisterBody, db: AsyncSession = Depends(get_db)):
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
async def login_account(body: AccountLoginBody, db: AsyncSession = Depends(get_db)):
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


@router.post("/google", response_model=AccountAuthResponse)
async def login_account_google(body: AccountGoogleLoginBody, db: AsyncSession = Depends(get_db)):
    google_payload = await _verify_google_id_token(body.id_token)

    aud = str(google_payload.get("aud") or "")
    configured_client_id = str(settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
    if configured_client_id and aud != configured_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google audience mismatch")

    fallback_client_id = str(body.client_id or "").strip()
    if not configured_client_id and fallback_client_id and aud != fallback_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google client mismatch")

    email = str(google_payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google account does not contain email")

    user = await _get_user_by_email(db, email)
    google_avatar = _extract_social_picture_url(google_payload)
    if user is None:
        role_id = await get_or_create_customer_role_id(db)
        full_name = str(google_payload.get("name") or email.split("@")[0] or "Khach hang").strip()
        user = User(
            email=email,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            full_name=full_name,
            avatar_url=google_avatar,
            is_active=True,
            role_id=role_id,
        )
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
    elif google_avatar and str(getattr(user, "avatar_url", "") or "").strip() != google_avatar:
        user.avatar_url = google_avatar
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


@router.post("/facebook", response_model=AccountAuthResponse)
async def login_account_facebook(body: AccountFacebookLoginBody, db: AsyncSession = Depends(get_db)):
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


def _coerce_dict(raw: object) -> dict:
    return raw if isinstance(raw, dict) else {}


def _coerce_list(raw: object) -> list[dict]:
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


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _compose_shipping_address(address_obj: dict) -> Optional[str]:
    if not isinstance(address_obj, dict):
        return None

    full_address = _pick_first_non_empty(address_obj, ("full_address", "fullAddress"))
    if isinstance(full_address, str) and full_address.strip():
        return full_address.strip()

    parts: list[str] = []
    street = _pick_first_non_empty(address_obj, ("address",))
    commune = _pick_first_non_empty(address_obj, ("commune_name", "ward_name", "communeName", "wardName"))
    district = _pick_first_non_empty(address_obj, ("district_name", "districtName"))
    province = _pick_first_non_empty(address_obj, ("province_name", "provinceName"))

    for value in (street, commune, district, province):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            parts.append(text)

    return ", ".join(parts) if parts else None


def _extract_pancake_order_data(detail: dict) -> dict:
    if not isinstance(detail, dict):
        return {}

    def _looks_like_order_payload(candidate: dict) -> bool:
        if not isinstance(candidate, dict):
            return False
        order_signals = (
            "bill_full_name",
            "bill_phone_number",
            "bill_address",
            "shipping_address",
            "status",
            "order_status",
            "custom_id",
            "total_amount",
            "total_price",
            "cod",
            "cash",
        )
        item_signals = ("product_id", "variation_id", "quantity", "variation_info")
        has_order_signal = any(candidate.get(key) is not None for key in order_signals)
        has_item_signal = any(candidate.get(key) is not None for key in item_signals)
        return has_order_signal or (not has_item_signal and candidate.get("id") is not None and candidate.get("status") is not None)

    direct_order = _coerce_dict(detail.get("order"))
    if direct_order and _looks_like_order_payload(direct_order):
        return direct_order

    data = _coerce_dict(detail.get("data"))
    nested_order = _coerce_dict(data.get("order"))
    if nested_order and _looks_like_order_payload(nested_order):
        return nested_order

    if data and _looks_like_order_payload(data):
        return data

    if _looks_like_order_payload(detail):
        return detail

    for key in ("orders", "results", "list"):
        for item in _coerce_list(data.get(key)):
            as_order = _coerce_dict(item.get("order"))
            if as_order and _looks_like_order_payload(as_order):
                return as_order
            if item and _looks_like_order_payload(item):
                return item

    for key in ("orders", "results", "list"):
        for item in _coerce_list(detail.get(key)):
            as_order = _coerce_dict(item.get("order"))
            if as_order and _looks_like_order_payload(as_order):
                return as_order
            if item and _looks_like_order_payload(item):
                return item

    from_order = _coerce_dict(detail.get("order"))
    if from_order and _looks_like_order_payload(from_order):
        return from_order
    if data and _looks_like_order_payload(data):
        return data
    return detail


def _extract_pancake_items(order_data: dict) -> list[dict]:
    for key in (
        "items",
        "order_items",
        "orderItems",
        "products",
        "line_items",
        "lineItems",
        "lines",
        "order_lines",
        "orderLines",
        "details",
    ):
        items = _coerce_list(order_data.get(key))
        if items:
            return items

    nested_order = _coerce_dict(order_data.get("order"))
    if nested_order:
        for key in (
            "items",
            "order_items",
            "orderItems",
            "products",
            "line_items",
            "lineItems",
            "lines",
            "order_lines",
            "orderLines",
            "details",
        ):
            items = _coerce_list(nested_order.get(key))
            if items:
                return items

    return []


def _map_pancake_item_to_response(item: dict) -> AccountOrderItemResponse:
    variation_info = _coerce_dict(item.get("variation_info"))
    product_id = _safe_int(
        _pick_first_non_empty(item, ("product_id", "productId", "id", "item_id", "itemId")),
        0,
    )
    variant_id_raw = _pick_first_non_empty(
        item,
        ("product_variant_id", "productVariantId", "variant_id", "variantId", "variation_id", "variationId"),
    )
    quantity = max(1, _safe_int(_pick_first_non_empty(item, ("quantity", "qty", "count", "amount")), 1))
    unit_price = _safe_float(
        _pick_first_non_empty(item, ("unit_price", "unitPrice", "price", "selling_price", "retail_price")),
        _safe_float(_pick_first_non_empty(variation_info, ("retail_price", "price")), 0.0),
    )
    subtotal = _safe_float(_pick_first_non_empty(item, ("subtotal", "line_total", "lineTotal", "total", "amount")), unit_price * quantity)
    name = str(
        _pick_first_non_empty(item, ("name", "title", "product_name", "productName", "variation_name"))
        or _pick_first_non_empty(variation_info, ("name", "detail"))
        or "Product"
    )
    sku_raw = _pick_first_non_empty(item, ("sku", "item_sku", "itemSku", "code", "barcode"))
    if sku_raw is None:
        sku_raw = _pick_first_non_empty(variation_info, ("barcode", "display_id", "product_display_id"))

    return AccountOrderItemResponse(
        product_id=product_id,
        product_variant_id=(_safe_int(variant_id_raw) if variant_id_raw is not None else None),
        name=name,
        sku=(str(sku_raw) if sku_raw is not None else None),
        quantity=quantity,
        unit_price=unit_price,
        subtotal=subtotal,
    )


def _extract_pancake_order_id(order_data: dict, fallback_id: Optional[str]) -> Optional[str]:
    # Use canonical id/order_id only. display_id is for display and can break detail fetch.
    candidate = _pick_first_non_empty(order_data, ("id", "order_id", "orderId"))
    if candidate is None:
        return fallback_id
    normalized = str(candidate).strip()
    return normalized or fallback_id


def _extract_pancake_items_from_any(detail: Optional[dict]) -> list[dict]:
    if not isinstance(detail, dict):
        return []

    for candidate in (
        _extract_pancake_order_data(detail),
        _coerce_dict(detail.get("data")),
        detail,
    ):
        if not isinstance(candidate, dict):
            continue
        items = _extract_pancake_items(candidate)
        if items:
            return items

    return []


def _normalize_phone(value: Optional[str]) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("84") and len(digits) >= 10:
        digits = f"0{digits[2:]}"
    return digits


def _payload_belongs_to_tracking_code(
    payload: Optional[dict],
    tracking_code: Optional[str],
    expected_pancake_order_id: Optional[str] = None,
) -> bool:
    if not isinstance(payload, dict):
        return False

    expected = str(tracking_code or "").strip()
    expected_order_id = str(expected_pancake_order_id or "").strip()
    if not expected:
        return True

    order_data = _extract_pancake_order_data(payload)
    custom_candidate = _pick_first_non_empty(
        order_data,
        ("custom_id", "customId", "tracking_code", "trackingCode"),
    )
    if custom_candidate is None:
        custom_candidate = _pick_first_non_empty(
            payload,
            ("custom_id", "customId", "tracking_code", "trackingCode"),
        )

    if custom_candidate is None:
        # Some Pancake payload variants omit custom_id; allow matching by order id as a safe fallback.
        if expected_order_id:
            payload_order_id = _extract_pancake_order_id(order_data, None)
            if payload_order_id is None:
                payload_order_id = _extract_pancake_order_id(payload, None)
            if payload_order_id is not None and str(payload_order_id).strip() == expected_order_id:
                return True
        return False

    return str(custom_candidate).strip() == expected


def _order_to_response_from_pancake(order: Order, detail: Optional[dict]) -> AccountOrderResponse:
    order_data = _extract_pancake_order_data(detail or {}) if isinstance(detail, dict) else {}
    shipping_address = _coerce_dict(order_data.get("shipping_address"))
    customer_data = _coerce_dict(order_data.get("customer"))
    detail_data = _coerce_dict(detail.get("data")) if isinstance(detail, dict) else {}
    detail_shipping = _coerce_dict(detail_data.get("shipping_address")) if detail_data else {}

    status_raw = _pick_first_non_empty(
        order_data,
        (
            "status",
            "order_status",
            "orderStatus",
            "state",
            "status_id",
            "statusId",
            "order_status_id",
            "orderStatusId",
            "status_name",
            "statusName",
            "order_status_name",
            "orderStatusName",
            "shipping_status",
            "shippingStatus",
            "fulfillment_status",
            "fulfillmentStatus",
        ),
    )
    if status_raw is None and isinstance(detail, dict):
        status_raw = _pick_first_non_empty(
            detail,
            (
                "status",
                "order_status",
                "orderStatus",
                "state",
                "status_id",
                "statusId",
                "order_status_id",
                "orderStatusId",
                "status_name",
                "statusName",
                "order_status_name",
                "orderStatusName",
                "shipping_status",
                "shippingStatus",
                "fulfillment_status",
                "fulfillmentStatus",
            ),
        )

    status_value = pancake_order_service.pancake_status_to_local_status(status_raw)
    raw_items = _extract_pancake_items(order_data)
    if not raw_items and isinstance(detail, dict):
        raw_items = _extract_pancake_items_from_any(detail)
    pancake_items = [_map_pancake_item_to_response(item) for item in raw_items]

    receiver_name = _pick_first_non_empty(
        order_data,
        ("bill_full_name", "receiver_name", "receiverName", "customer_name", "customerName"),
    )
    if receiver_name is None:
        receiver_name = _pick_first_non_empty(shipping_address, ("full_name", "name", "receiver_name", "receiverName"))
    if receiver_name is None:
        receiver_name = _pick_first_non_empty(customer_data, ("name", "full_name", "fullName"))
    if receiver_name is None and detail_data:
        receiver_name = _pick_first_non_empty(
            detail_data,
            ("bill_full_name", "receiver_name", "receiverName", "customer_name", "customerName"),
        )
    if receiver_name is None:
        receiver_name = _pick_first_non_empty(detail_shipping, ("full_name", "name", "receiver_name", "receiverName"))
    if receiver_name is None and isinstance(detail, dict):
        receiver_name = _pick_first_non_empty(
            detail,
            ("bill_full_name", "receiver_name", "receiverName", "customer_name", "customerName"),
        )

    receiver_phone = _pick_first_non_empty(order_data, ("bill_phone_number", "receiver_phone", "receiverPhone", "phone"))
    if receiver_phone is None:
        receiver_phone = _pick_first_non_empty(shipping_address, ("phone_number", "phone", "receiver_phone", "receiverPhone"))
    if receiver_phone is None and detail_data:
        receiver_phone = _pick_first_non_empty(detail_data, ("bill_phone_number", "receiver_phone", "receiverPhone", "phone"))
    if receiver_phone is None:
        receiver_phone = _pick_first_non_empty(detail_shipping, ("phone_number", "phone", "receiver_phone", "receiverPhone"))

    receiver_address = _pick_first_non_empty(order_data, ("bill_address", "receiver_address", "receiverAddress", "address", "full_address"))
    if receiver_address is None:
        receiver_address = _compose_shipping_address(shipping_address)
    if receiver_address is None and detail_data:
        receiver_address = _pick_first_non_empty(detail_data, ("bill_address", "receiver_address", "receiverAddress", "address", "full_address"))
    if receiver_address is None:
        receiver_address = _compose_shipping_address(detail_shipping)
    payment_method = _pick_first_non_empty(order_data, ("payment_method", "paymentMethod", "payment_type", "paymentType", "pay_method", "payMethod"))
    payment_status = _pick_first_non_empty(order_data, ("payment_status", "paymentStatus", "payment_state", "paymentState", "is_paid", "isPaid"))
    total_amount = _pick_first_non_empty(order_data, ("total_amount", "totalAmount", "total", "grand_total", "grandTotal", "total_payment", "totalPayment", "cod"))
    created_at_raw = _pick_first_non_empty(order_data, ("created_at", "createdAt", "inserted_at", "created"))

    normalized_payment_status = str(payment_status or order.payment_status or "pending").strip().lower()
    if normalized_payment_status in {"true", "1", "paid", "da_thanh_toan", "đã thanh toán"}:
        normalized_payment_status = "paid"
    elif normalized_payment_status in {"false", "0", "unpaid", "pending", "cho_thanh_toan", "chờ thanh toán"}:
        normalized_payment_status = "pending"

    return AccountOrderResponse(
        id=int(order.id),
        tracking_code=order.tracking_code,
        pancake_order_id=_extract_pancake_order_id(order_data, order.pancake_order_id),
        status=status_value,
        pancake_status_raw=status_raw,
        payment_status=normalized_payment_status,
        payment_method=str(payment_method or order.payment_method or "cod"),
        receiver_name=str(receiver_name or "") or None,
        receiver_phone=str(receiver_phone or order.receiver_phone or "") or None,
        receiver_address=str(receiver_address or "") or None,
        total_amount=_safe_float(total_amount, float(order.total_amount or 0)),
        created_at=(str(created_at_raw) if created_at_raw is not None else (order.created_at.isoformat() if order.created_at else "")),
        items=pancake_items,
    )


async def _claim_legacy_guest_orders_by_phone(db: AsyncSession, user: User, receiver_phone: Optional[str]) -> int:
    normalized_phone = _normalize_phone(receiver_phone)
    if not normalized_phone:
        return 0

    stmt = (
        select(Order)
        .where(Order.user_id == 0, Order.deleted_at.is_(None), Order.pancake_order_id.is_not(None))
        .order_by(Order.id.desc())
        .limit(300)
    )
    guest_orders = (await db.execute(stmt)).scalars().all()
    if not guest_orders:
        return 0

    claimed = 0
    for order in guest_orders:
        # Fast path: receiver phone is already stored locally when order is created.
        if _normalize_phone(str(order.receiver_phone or "")) != normalized_phone:
            continue

        order.user_id = int(user.id)
        claimed += 1

    if claimed > 0:
        await db.flush()
        await db.commit()
    return claimed


@router.get("/orders", response_model=AccountOrdersResponse)
async def get_my_orders(
    receiver_phone: Optional[str] = Query(default=None, alias="receiverPhone"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_account_user),
):
    await _claim_legacy_guest_orders_by_phone(db, current_user, receiver_phone)

    live_sync_limit = 12

    stmt = (
        select(Order)
        .where(
            Order.user_id == int(current_user.id),
            Order.deleted_at.is_(None),
            Order.pancake_order_id.is_not(None),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(40)
    )
    orders = (await db.execute(stmt)).scalars().all()

    initial_details: list[Optional[dict]] = [None] * len(orders)
    if pancake_order_service.is_enabled() and pancake_order_service.is_configured() and orders:
        semaphore = asyncio.Semaphore(8)
        refresh_indices = [
            idx for idx, order in enumerate(orders)
            if idx < live_sync_limit or not isinstance(order.pancake_payload, dict)
        ]

        async def _fetch_detail_by_id(idx: int, order_obj: Order) -> tuple[int, Optional[dict]]:
            tracking_code_inner = str(order_obj.tracking_code or "").strip()
            pancake_order_id_inner = str(order_obj.pancake_order_id or "").strip()
            if not pancake_order_id_inner:
                return idx, None

            async with semaphore:
                detail = await pancake_order_service.get_order_detail(
                    pancake_order_id_inner,
                    expected_custom_id=tracking_code_inner or None,
                )
                return idx, detail if isinstance(detail, dict) else None

        batch_results = await asyncio.gather(
            *[_fetch_detail_by_id(idx, orders[idx]) for idx in refresh_indices]
        )
        for idx, detail in batch_results:
            initial_details[idx] = detail

    result: list[AccountOrderResponse] = []
    has_updates = False
    for idx, order in enumerate(orders):
        tracking_code = str(order.tracking_code or "").strip()
        allow_live_sync = idx < live_sync_limit
        pancake_detail = initial_details[idx] if idx < len(initial_details) else None
        if pancake_order_service.is_enabled() and pancake_order_service.is_configured():
            # Slow fallback: resolve by tracking_code/custom_id only when direct id lookup fails.
            if pancake_detail is None and tracking_code and allow_live_sync:
                by_custom = await pancake_order_service.find_order_by_custom_id(tracking_code)
                if isinstance(by_custom, dict):
                    recovered_id = _extract_pancake_order_id(_extract_pancake_order_data(by_custom), None)
                    if recovered_id and str(order.pancake_order_id or "").strip() != str(recovered_id).strip():
                        order.pancake_order_id = str(recovered_id).strip()
                        has_updates = True

                    if recovered_id:
                        refetched = await pancake_order_service.get_order_detail(
                            str(recovered_id),
                            expected_custom_id=tracking_code or None,
                        )
                        pancake_detail = refetched if isinstance(refetched, dict) else by_custom
                    else:
                        pancake_detail = by_custom

        effective_detail = (
            pancake_detail
            if isinstance(pancake_detail, dict)
            else (
                order.pancake_payload
                if _payload_belongs_to_tracking_code(
                    order.pancake_payload if isinstance(order.pancake_payload, dict) else None,
                    tracking_code,
                    str(order.pancake_order_id or "") or None,
                )
                else None
            )
        )

        response_item = _order_to_response_from_pancake(order, effective_detail)

        # When Pancake search returns summary rows (no items), force a strict detail fetch.
        if (
            len(response_item.items) == 0
            and pancake_order_service.is_enabled()
            and pancake_order_service.is_configured()
            and allow_live_sync
        ):
            canonical_id = str(response_item.pancake_order_id or order.pancake_order_id or "").strip()
            if canonical_id:
                strict_detail = await pancake_order_service.get_order_detail(
                    canonical_id,
                    expected_custom_id=tracking_code or None,
                )
                strict_view = _order_to_response_from_pancake(order, strict_detail if isinstance(strict_detail, dict) else None)
                if len(strict_view.items) > 0:
                    response_item = strict_view
                    if isinstance(strict_detail, dict):
                        effective_detail = strict_detail
                        if order.pancake_payload != strict_detail:
                            order.pancake_payload = strict_detail
                            has_updates = True

        result.append(response_item)

        if str(order.status or "") != str(response_item.status or ""):
            order.status = response_item.status
            has_updates = True
        if str(order.payment_status or "") != str(response_item.payment_status or ""):
            order.payment_status = response_item.payment_status
            has_updates = True
        # Keep mapping in sync with verified detail.
        recovered_pancake_id = response_item.pancake_order_id if isinstance(effective_detail, dict) else None
        if recovered_pancake_id and str(order.pancake_order_id or "").strip() != str(recovered_pancake_id).strip():
            order.pancake_order_id = str(recovered_pancake_id).strip()
            has_updates = True
        if isinstance(pancake_detail, dict) and order.pancake_payload != pancake_detail:
            order.pancake_payload = pancake_detail
            has_updates = True

    if has_updates:
        await db.flush()
        await db.commit()

    return AccountOrdersResponse(success=True, data=result)


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
            Order.pancake_order_id.is_not(None),
        )
        .limit(1)
    )
    order = (await db.execute(stmt)).scalars().first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if not pancake_order_service.is_enabled() or not pancake_order_service.is_configured():
        raise HTTPException(status_code=503, detail="Pancake is not configured for order cancellation")

    tracking_code = str(order.tracking_code or "").strip()

    latest_detail = None
    if tracking_code:
        # Always resolve by custom_id first for cancellation to avoid updating the wrong Pancake order.
        by_custom = await pancake_order_service.find_order_by_custom_id(tracking_code)
        if isinstance(by_custom, dict):
            recovered_for_detail = _extract_pancake_order_id(_extract_pancake_order_data(by_custom), None)
            if recovered_for_detail:
                if str(order.pancake_order_id or "").strip() != str(recovered_for_detail).strip():
                    order.pancake_order_id = str(recovered_for_detail).strip()

                refetched = await pancake_order_service.get_order_detail(
                    str(recovered_for_detail),
                    expected_custom_id=tracking_code or None,
                )
                latest_detail = refetched if isinstance(refetched, dict) else by_custom
            else:
                latest_detail = by_custom

    if latest_detail is None:
        latest_detail = await pancake_order_service.get_order_detail(
            str(order.pancake_order_id or ""),
            expected_custom_id=tracking_code or None,
        )

    if isinstance(latest_detail, dict):
        recovered = _extract_pancake_order_id(_extract_pancake_order_data(latest_detail), str(order.pancake_order_id or ""))
        if recovered and str(recovered).strip() and str(order.pancake_order_id or "").strip() != str(recovered).strip():
            order.pancake_order_id = str(recovered).strip()

    effective_detail = latest_detail if isinstance(latest_detail, dict) else (order.pancake_payload if isinstance(order.pancake_payload, dict) else None)

    if tracking_code and not _payload_belongs_to_tracking_code(
        effective_detail if isinstance(effective_detail, dict) else None,
        tracking_code,
        str(order.pancake_order_id or "") or None,
    ):
        raise HTTPException(
            status_code=409,
            detail="Không thể xác minh mapping đơn Pancake theo mã đơn nội bộ. Vui lòng tải lại danh sách đơn và thử lại.",
        )

    current_view = _order_to_response_from_pancake(order, effective_detail)
    current_status = str(current_view.status or "").strip().lower()

    if current_status in {"shipped", "delivered"}:
        raise HTTPException(status_code=409, detail="Order is already shipping/delivered and cannot be cancelled")

    if current_status == "cancelled":
        if isinstance(latest_detail, dict) and order.pancake_payload != latest_detail:
            order.pancake_payload = latest_detail
            await db.flush()
            await db.commit()
        return AccountOrderActionResponse(success=True, data=current_view)

    try:
        cancel_result = await pancake_order_service.update_order_status(
            pancake_order_id=str(order.pancake_order_id),
            local_status="cancelled",
            pancake_status=6,
        )
    except Exception as exc:
        if pancake_order_service.is_permission_sync_error(exc):
            raise HTTPException(
                status_code=403,
                detail="API key Pancake hiện tại không có quyền hủy/cập nhật trạng thái đơn hàng này. Vui lòng cấp quyền Update Order cho API key.",
            )
        raise HTTPException(status_code=502, detail=f"Failed to cancel order on Pancake: {exc}")

    refreshed_detail = await pancake_order_service.get_order_detail(
        str(order.pancake_order_id or ""),
        expected_custom_id=str(order.tracking_code or "").strip() or None,
    )
    final_detail = (
        refreshed_detail
        if isinstance(refreshed_detail, dict)
        else (cancel_result if isinstance(cancel_result, dict) else effective_detail)
    )

    final_view = _order_to_response_from_pancake(order, final_detail if isinstance(final_detail, dict) else None)
    order.status = OrderStatus.CANCELLED.value
    order.payment_status = str(final_view.payment_status or order.payment_status or "pending")
    if isinstance(final_detail, dict):
        order.pancake_payload = final_detail

    await db.flush()
    await db.commit()

    final_view = final_view.model_copy(update={"status": OrderStatus.CANCELLED.value})
    return AccountOrderActionResponse(success=True, data=final_view)


@router.post("/orders/repair-mapping", response_model=AccountOrderRepairSummaryResponse)
async def repair_my_order_mapping(
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
        .limit(200)
    )
    orders = (await db.execute(stmt)).scalars().all()

    repaired = 0
    for order in orders:
        tracking_code = str(order.tracking_code or "").strip()
        if not tracking_code:
            continue

        detail = await pancake_order_service.find_order_by_custom_id(tracking_code)
        if not isinstance(detail, dict):
            continue

        recovered_id = _extract_pancake_order_id(_extract_pancake_order_data(detail), None)
        changed = False
        if recovered_id and str(order.pancake_order_id or "").strip() != str(recovered_id).strip():
            order.pancake_order_id = str(recovered_id).strip()
            changed = True

        if order.pancake_payload != detail:
            order.pancake_payload = detail
            changed = True

        if changed:
            repaired += 1

    if repaired > 0:
        await db.flush()
        await db.commit()

    return AccountOrderRepairSummaryResponse(success=True, repaired=repaired, scanned=len(orders))


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
