from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.role_helpers import is_customer_role
from app.domain.models.user import User


bearer_scheme = HTTPBearer(auto_error=False)
STOREFRONT_TOKEN_SCOPE = "storefront"


async def _is_storefront_customer_user(db: AsyncSession, user: User) -> bool:
    role_id = getattr(user, "role_id", None)
    if role_id is None:
        return False
    return await is_customer_role(db, role_id)


async def get_optional_account_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not credentials or not credentials.credentials:
        return None

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_scope = str(payload.get("scope") or "").strip().lower()
        if token_scope and token_scope != STOREFRONT_TOKEN_SCOPE:
            return None
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            return None
        user_id = int(user_id_raw)
    except (JWTError, ValueError):
        return None

    user = await db.get(User, user_id)
    if not user:
        return None
    if not bool(getattr(user, "is_active", True)):
        return None
    if not await _is_storefront_customer_user(db, user):
        return None
    return user


async def get_current_account_user(
    current_user: Optional[User] = Depends(get_optional_account_user),
) -> User:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid access token")
    return current_user
