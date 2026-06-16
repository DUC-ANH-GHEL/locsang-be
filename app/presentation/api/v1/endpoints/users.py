from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta

from app.core.database import get_db
from app.core.role_helpers import is_admin_role
from app.core.security import create_access_token, verify_password
from app.core.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.application.dto.user import UserCreate, UserUpdate, UserResponse, UserLogin, Token
from app.application.services.user_service import UserService
from app.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(prefix="/users", tags=["users"])
ADMIN_TOKEN_SCOPE = "admin"

@router.post("/login", response_model=Token)
async def login(
    login_data: UserLogin,
    _limited: None = Depends(rate_limit("admin-login", limit=8, window_seconds=60)),
    db: AsyncSession = Depends(get_db)
):
    """Login user and return access token."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    user = await user_service.get_by_email(login_data.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This admin account is disabled",
        )

    if not await is_admin_role(db, getattr(user, "role_id", None)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not allowed to access admin",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "scope": ADMIN_TOKEN_SCOPE}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/verify-token")
async def verify_token(
    current_user = Depends(get_current_user)
):
    """Verify token."""
    return {
        "message": "Token is valid",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name
        }
    }

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new user."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    return await user_service.create(user)

@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: UserResponse = Depends(get_current_user)
):
    """Get current user information."""
    return current_user

@router.put("/me", response_model=UserResponse)
async def update_user_me(
    user: UserUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user information."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    return await user_service.update(current_user.id, user)

@router.get("/{user_id}", response_model=UserResponse)
async def read_user(
    user_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    user = await user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user: UserUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user by ID."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    updated_user = await user_service.update(user_id, user)
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return updated_user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete user by ID."""
    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    if not await user_service.delete(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
