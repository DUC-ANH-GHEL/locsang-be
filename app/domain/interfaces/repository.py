from typing import Generic, TypeVar, List, Optional
from abc import ABC, abstractmethod

T = TypeVar('T')

class BaseRepository(Generic[T], ABC):
    """Base repository interface defining common CRUD operations"""

    @abstractmethod
    async def create(self, entity: T) -> T:
        """Create a new entity"""
        pass

    @abstractmethod
    async def get_by_id(self, id: int) -> Optional[T]:
        """Get entity by id"""
        pass

    @abstractmethod
    async def get_all(self) -> List[T]:
        """Get all entities"""
        pass

    @abstractmethod
    async def update(self, id: int, entity: T) -> Optional[T]:
        """Update an existing entity"""
        pass

    @abstractmethod
    async def delete(self, id: int) -> bool:
        """Delete an entity"""
        pass

    @abstractmethod
    async def exists(self, id: int) -> bool:
        """Check if entity exists"""
        pass
