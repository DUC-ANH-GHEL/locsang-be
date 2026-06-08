from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.user import User
from app.infrastructure.repositories.base import SQLAlchemyRepository
from app.core.exceptions import NotFoundException

class UserRepository(SQLAlchemyRepository[User]):
    """User repository implementation"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        query = select(User).where(User.email == email)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        query = select(User).where(User.username == username)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_users(self) -> List[User]:
        """Get all active users"""
        query = select(User).where(User.is_active == True)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_users_by_role(self, role_id: int) -> List[User]:
        """Get users by role"""
        query = select(User).where(User.role_id == role_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())
