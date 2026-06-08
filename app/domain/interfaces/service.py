from typing import Generic, TypeVar, List, Optional
from abc import ABC, abstractmethod

T = TypeVar('T')
CreateDTO = TypeVar('CreateDTO')
UpdateDTO = TypeVar('UpdateDTO')

class BaseService(Generic[T, CreateDTO, UpdateDTO], ABC):
    """Base service interface defining common business operations"""

    @abstractmethod
    async def create(self, dto: CreateDTO) -> T:
        """Create a new entity from DTO"""
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
    async def update(self, id: int, dto: UpdateDTO) -> Optional[T]:
        """Update an existing entity from DTO"""
        pass

    @abstractmethod
    async def delete(self, id: int) -> bool:
        """Delete an entity"""
        pass

    @abstractmethod
    async def validate(self, dto: CreateDTO | UpdateDTO) -> bool:
        """Validate DTO data"""
        pass
