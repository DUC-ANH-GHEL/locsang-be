from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.role_helpers import is_admin_role
from app.domain.models.user import User
from app.infrastructure.repositories.user_repository import UserRepository
from app.core.exceptions import NotFoundException

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/users/login")
ADMIN_TOKEN_SCOPE = "admin"

async def _ensure_admin_role(db: AsyncSession, user: User) -> User:
    role_id = getattr(user, "role_id", None)
    if role_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")

    if not await is_admin_role(db, role_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")

    return user

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_scope = str(payload.get("scope") or "").strip().lower()
        if token_scope and token_scope != ADMIN_TOKEN_SCOPE:
            raise credentials_exception
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_repository = UserRepository(db)
    try:
        user = await user_repository.get_by_id(int(user_id))
    except NotFoundException:
        raise credentials_exception
    return await _ensure_admin_role(db, user)

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user
