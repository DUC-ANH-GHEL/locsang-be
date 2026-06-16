from typing import Optional, List
from app.domain.models.user import User
from app.infrastructure.repositories.user_repository import UserRepository
from app.application.services.base import BaseServiceImpl
from app.application.dto.user import UserCreate, UserUpdate, UserResponse
from app.core.exceptions import ValidationException
from app.core.security import get_password_hash, verify_password
from datetime import datetime
from app.core.security import decode_token


class UserService(BaseServiceImpl[User, UserCreate, UserUpdate]):
    """User service implementation"""

    def __init__(self, repository: UserRepository):
        super().__init__(repository)
        self.repository = repository

    async def create(self, dto: UserCreate) -> User:
        """Create a new user"""
        # Check if email or username already exists
        if await self.repository.get_by_email(dto.email):
            raise ValidationException("Email already registered")
        if await self.repository.get_by_username(dto.username):
            raise ValidationException("Username already taken")

        # Create user with hashed password
        user = await self._map_dto_to_entity(dto)
        return await self.repository.create(user)

    async def update(self, id: int, dto: UserUpdate) -> Optional[User]:
        """Update a user"""
        user = await self.repository.get_by_id(id)
        if not user:
            return None

        # Check if new email or username already exists
        if dto.email and dto.email != user.email:
            if await self.repository.get_by_email(dto.email):
                raise ValidationException("Email already registered")
        if dto.username and dto.username != user.username:
            if await self.repository.get_by_username(dto.username):
                raise ValidationException("Username already taken")

        # Update user fields
        update_data = dto.dict(exclude_unset=True)
        if "password" in update_data:
            update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

        for field, value in update_data.items():
            setattr(user, field, value)

        return await self.repository.update(id, user)

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate a user"""
        user = await self.repository.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return await self.repository.get_by_email(email)

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return await self.repository.get_by_username(username)

    async def get_active_users(self) -> List[User]:
        """Get all active users"""
        return await self.repository.get_active_users()

    async def get_users_by_role(self, role_id: int) -> List[User]:
        """Get users by role"""
        return await self.repository.get_users_by_role(role_id)

    async def verify_token(self, token: str) -> bool:
        """Verify token"""

        try:
            payload = decode_token(token)
            if payload is None:
                return False

            # Check if token is expired
            exp = payload.get("exp")
            if exp is None:
                return False

            # Convert exp to datetime and check if expired
            exp_datetime = datetime.fromtimestamp(exp)
            if exp_datetime < datetime.utcnow():
                return False

            return True

        except Exception:
            return False

    async def _map_dto_to_entity(self, dto: UserCreate | UserUpdate) -> User:
        """Map DTO to User entity"""
        if isinstance(dto, UserCreate):
            return User(
                email=dto.email,
                username=dto.username,
                hashed_password=get_password_hash(dto.password),
                full_name=dto.full_name,
                phone=dto.phone,
                is_active=dto.is_active,
                role_id=dto.role_id
            )
        else:
            return User(**dto.dict(exclude_unset=True))
