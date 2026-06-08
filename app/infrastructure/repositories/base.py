from typing import Generic, TypeVar, List, Optional, Type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.sql import Select

from app.domain.interfaces.repository import BaseRepository
from app.core.exceptions import NotFoundException, DatabaseException

T = TypeVar('T')

class SQLAlchemyRepository(BaseRepository[T], Generic[T]):
    """Base repository implementation using SQLAlchemy"""

    def __init__(self, session: AsyncSession, model_class: Type[T]):
        self.session = session
        self.model_class = model_class

    async def create(self, entity: T) -> T:
        try:
            self.session.add(entity)
            await self.session.commit()
            await self.session.refresh(entity)
            return entity
        except Exception as e:
            await self.session.rollback()
            raise DatabaseException(f"Error creating entity: {str(e)}")

    async def get_by_id(self, id: int) -> Optional[T]:
        try:
            result = await self.session.get(self.model_class, id)
            if not result:
                raise NotFoundException(f"{self.model_class.__name__} with id {id} not found")
            return result
        except NotFoundException:
            raise
        except Exception as e:
            raise DatabaseException(f"Error getting entity by id: {str(e)}")

    async def get_all(self) -> List[T]:
        try:
            query = select(self.model_class)
            result = await self.session.execute(query)
            return list(result.scalars().all())
        except Exception as e:
            raise DatabaseException(f"Error getting all entities: {str(e)}")

    async def update(self, id: int, entity: T) -> Optional[T]:
        try:
            existing = await self.get_by_id(id)  # Check if exists
            for key, value in entity.__dict__.items():
                if not key.startswith('_'):
                    setattr(existing, key, value)
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        except NotFoundException:
            raise
        except Exception as e:
            await self.session.rollback()
            raise DatabaseException(f"Error updating entity: {str(e)}")

    async def delete(self, id: int) -> bool:
        try:
            await self.get_by_id(id)  # Check if exists
            stmt = delete(self.model_class).where(self.model_class.id == id)
            await self.session.execute(stmt)
            await self.session.commit()
            return True
        except NotFoundException:
            raise
        except Exception as e:
            await self.session.rollback()
            raise DatabaseException(f"Error deleting entity: {str(e)}")

    async def exists(self, id: int) -> bool:
        try:
            result = await self.session.get(self.model_class, id)
            return result is not None
        except Exception as e:
            raise DatabaseException(f"Error checking entity existence: {str(e)}")

    def _build_query(self, **filters) -> Select:
        """Build a query with filters"""
        query = select(self.model_class)
        for key, value in filters.items():
            if hasattr(self.model_class, key):
                query = query.where(getattr(self.model_class, key) == value)
        return query
