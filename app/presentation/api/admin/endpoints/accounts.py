from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.role_helpers import ADMIN_ROLE_NAMES, get_role_name_by_id, is_admin_role
from app.core.security import get_password_hash, verify_password
from app.domain.models.role import Role
from app.domain.models.user import User


router = APIRouter(prefix="/accounts", tags=["admin-accounts"])
PHONE_LOGIN_EMAIL_DOMAIN = "phone.locsang.local"


class AdminAccountCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    is_active: bool = True


class AdminAccountUpdate(BaseModel):
    email: Optional[str] = Field(default=None, min_length=3, max_length=160)
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    is_active: Optional[bool] = None


class ChangePasswordBody(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


def _validate_password_strength(password: str) -> None:
    has_letter = any(char.isalpha() for char in password)
    has_number = any(char.isdigit() for char in password)
    if not has_letter or not has_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mật khẩu cần có ít nhất 8 ký tự, gồm chữ và số.",
        )


def _normalize_phone(value: str) -> Optional[str]:
    compact = re.sub(r"[\s\-().]", "", value.strip())
    if compact.startswith("+84"):
        compact = "0" + compact[3:]
    elif compact.startswith("84") and len(compact) in {11, 12}:
        compact = "0" + compact[2:]
    if compact.isdigit() and 9 <= len(compact) <= 11:
        return compact
    return None


def _is_valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value.strip()))


def _phone_login_email(phone: str) -> str:
    return f"phone-{phone}@{PHONE_LOGIN_EMAIL_DOMAIN}"


def _is_phone_login_email(value: str | None) -> bool:
    return bool(value and value.endswith(f"@{PHONE_LOGIN_EMAIL_DOMAIN}"))


def _normalize_login_identifier(value: str) -> tuple[str, str, Optional[str]]:
    raw = value.strip()
    email = raw.lower()
    if _is_valid_email(email):
        return email, email, None

    phone = _normalize_phone(raw)
    if phone:
        return phone, _phone_login_email(phone), phone

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Tài khoản đăng nhập phải là email hợp lệ hoặc số điện thoại hợp lệ.",
    )


async def _active_admin_count(db: AsyncSession) -> int:
    stmt = (
        select(func.count(User.id))
        .join(Role, Role.id == User.role_id)
        .where(User.is_active.is_(True), func.lower(Role.name).in_(tuple(sorted(ADMIN_ROLE_NAMES))))
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


def _account_response(user: User, role_name: str = "admin") -> dict[str, Any]:
    phone = getattr(user, "phone", None)
    public_email = "" if _is_phone_login_email(user.email) else user.email
    return {
        "id": int(user.id),
        "email": public_email,
        "phone": phone,
        "login_identifier": phone or public_email,
        "full_name": user.full_name,
        "is_active": bool(user.is_active),
        "role_id": int(user.role_id),
        "role_name": role_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


async def _get_or_create_admin_role_id(db: AsyncSession) -> int:
    admin_names = tuple(sorted(ADMIN_ROLE_NAMES))
    stmt = select(Role).where(func.lower(Role.name).in_(admin_names)).order_by(Role.id.asc()).limit(1)
    role = (await db.execute(stmt)).scalar_one_or_none()
    if role is not None:
        return int(role.id)

    role = Role(name="admin", description="Lộc Sang admin")
    db.add(role)
    await db.flush()
    return int(role.id)


async def _find_existing_login(db: AsyncSession, email: str, phone: Optional[str], exclude_user_id: Optional[int] = None):
    filters = [func.lower(User.email) == email.lower()]
    if phone:
        filters.append(User.phone == phone)
    stmt = select(User).where(or_(*filters))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    stmt = stmt.limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("")
async def list_admin_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
    users = (await db.execute(stmt)).scalars().all()

    data = []
    for user in users:
        role_name = await get_role_name_by_id(db, user.role_id)
        if await is_admin_role(db, user.role_id):
            data.append(_account_response(user, role_name or "admin"))

    return {"data": data}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_admin_account(
    payload: AdminAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _login_identifier, email, phone = _normalize_login_identifier(payload.email)
    full_name = payload.full_name.strip()
    _validate_password_strength(payload.password)

    if await _find_existing_login(db, email, phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tài khoản đăng nhập này đã tồn tại.")

    try:
        role_id = await _get_or_create_admin_role_id(db)
        now = datetime.utcnow()
        user = User(
            email=email,
            phone=phone,
            full_name=full_name,
            hashed_password=get_password_hash(payload.password),
            is_active=bool(payload.is_active),
            role_id=role_id,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tài khoản đăng nhập này đã tồn tại.")
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không tạo được tài khoản admin.",
        )

    return {"success": True, "data": _account_response(user)}


@router.patch("/{account_id}")
async def update_admin_account(
    account_id: int,
    payload: AdminAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await db.get(User, account_id)
    if user is None or not await is_admin_role(db, user.role_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản admin.")

    update_data = payload.model_dump(exclude_unset=True)
    if "email" in update_data and update_data["email"] is not None:
        _login_identifier, email, phone = _normalize_login_identifier(str(update_data["email"]))
        if await _find_existing_login(db, email, phone, exclude_user_id=account_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tài khoản đăng nhập này đã tồn tại.")
        user.email = email
        user.phone = phone

    if "full_name" in update_data and update_data["full_name"] is not None:
        user.full_name = str(update_data["full_name"]).strip()

    if "password" in update_data and update_data["password"]:
        _validate_password_strength(str(update_data["password"]))
        user.hashed_password = get_password_hash(str(update_data["password"]))

    if "is_active" in update_data and update_data["is_active"] is not None:
        next_active = bool(update_data["is_active"])
        if bool(user.is_active) and not next_active and await _active_admin_count(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phải luôn có ít nhất 1 tài khoản admin đang hoạt động.",
            )
        if int(current_user.id) == int(user.id) and not next_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tắt chính tài khoản đang đăng nhập.",
            )
        user.is_active = next_active

    user.updated_at = datetime.utcnow()
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tài khoản đăng nhập này đã tồn tại.")

    role_name = await get_role_name_by_id(db, user.role_id)
    return {"success": True, "data": _account_response(user, role_name or "admin")}


@router.delete("/{account_id}")
async def delete_admin_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = await db.get(User, account_id)
    if user is None or not await is_admin_role(db, user.role_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản admin.")
    if int(current_user.id) == int(user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể xóa chính tài khoản đang đăng nhập.",
        )
    if bool(user.is_active) and await _active_admin_count(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phải luôn có ít nhất 1 tài khoản admin đang hoạt động.",
        )

    try:
        await db.delete(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể xóa tài khoản đang có dữ liệu liên quan. Hãy tắt đăng nhập thay thế.",
        )

    return {"success": True}


@router.post("/change-password")
async def change_admin_password(
    payload: ChangePasswordBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_password_strength(payload.new_password)

    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu hiện tại không đúng.")

    if verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu mới không được trùng mật khẩu hiện tại.",
        )

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.updated_at = datetime.utcnow()
    await db.commit()

    return {"success": True, "message": "Đã đổi mật khẩu."}
