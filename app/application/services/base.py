from typing import Generic, TypeVar, List, Optional
from app.domain.interfaces.service import BaseService
from app.domain.interfaces.repository import BaseRepository
from app.core.exceptions import ValidationException

T = TypeVar('T')
CreateDTO = TypeVar('CreateDTO')
UpdateDTO = TypeVar('UpdateDTO')

class BaseServiceImpl(BaseService[T, CreateDTO, UpdateDTO], Generic[T, CreateDTO, UpdateDTO]):
    """Base service implementation"""

    def __init__(self, repository: BaseRepository[T]):
        self.repository = repository

    async def create(self, dto: CreateDTO) -> T:
        """Create a new entity from DTO"""
        if not await self.validate(dto):
            raise ValidationException("Invalid data provided")
        entity = self._map_dto_to_entity(dto)
        return await self.repository.create(entity)

    async def get_by_id(self, id: int) -> Optional[T]:
        """Get entity by id"""
        return await self.repository.get_by_id(id)

    async def get_all(self) -> List[T]:
        """Get all entities"""
        return await self.repository.get_all()

    async def update(self, id: int, dto: UpdateDTO) -> Optional[T]:
        """Update an existing entity from DTO"""
        if not await self.validate(dto):
            raise ValidationException("Invalid data provided")
        entity = await self._map_dto_to_entity(dto)
        return await self.repository.update(id, entity)

    async def delete(self, id: int) -> bool:
        """Delete an entity"""
        return await self.repository.delete(id)

    async def validate(self, dto: CreateDTO | UpdateDTO) -> bool:
        """Validate DTO data"""
        # Override this method in child classes to implement specific validation logic
        return True

    async def _map_dto_to_entity(self, dto: CreateDTO | UpdateDTO) -> T:
        """Map DTO to entity"""
        # Override this method in child classes to implement specific mapping logic
        raise NotImplementedError("_map_dto_to_entity must be implemented in child classes")
