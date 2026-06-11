from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.role_helpers import ADMIN_ROLE_NAMES, get_role_name_by_id, is_admin_role
from app.core.security import get_password_hash, verify_password
from app.core.database import get_db
from app.domain.models.role import Role
from app.domain.models.user import User


router = APIRouter(prefix="/accounts", tags=["admin-accounts"])


class AdminAccountCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    is_active: bool = True


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


def _account_response(user: User, role_name: str = "admin") -> dict[str, Any]:
    return {
        "id": int(user.id),
        "email": user.email,
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
    email = payload.email.strip().lower()
    full_name = payload.full_name.strip()
    _validate_password_strength(payload.password)

    existing = (
        await db.execute(select(User).where(func.lower(User.email) == email).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email này đã có tài khoản admin.")

    try:
        role_id = await _get_or_create_admin_role_id(db)
        now = datetime.utcnow()
        user = User(
            email=email,
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email này đã có tài khoản admin.")
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Không tạo được tài khoản admin.")

    return {"success": True, "data": _account_response(user)}


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu mới không được trùng mật khẩu hiện tại.")

    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.updated_at = datetime.utcnow()
    await db.commit()

    return {"success": True, "message": "Đã đổi mật khẩu."}
