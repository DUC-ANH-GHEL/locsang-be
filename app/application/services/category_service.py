from typing import Optional, List
from sqlalchemy.orm import Session
from app.domain.models.category import Category
from app.infrastructure.repositories.category_repository import CategoryRepository
from app.application.services.base import BaseServiceImpl
from app.application.dto.category import CategoryCreate, CategoryUpdate, CategoryResponse
from app.core.exceptions import ValidationException

class CategoryService(BaseServiceImpl[Category, CategoryCreate, CategoryUpdate]):
    """Category service implementation"""

    def __init__(self, db: Session):
        super().__init__(CategoryRepository(db))
        self.db = db

    def create(self, category: CategoryCreate) -> Category:
        """Create a new category"""
        # Check if name already exists
        if self.repository.get_by_name(category.name):
            raise ValidationException("Category name already exists")

        db_category = Category(**category.model_dump())
        self.db.add(db_category)
        self.db.commit()
        self.db.refresh(db_category)
        return db_category

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Category]:
        """Get all categories"""
        return self.db.query(Category).offset(skip).limit(limit).all()

    def get_by_id(self, category_id: int) -> Optional[Category]:
        """Get category by ID"""
        return self.db.query(Category).filter(Category.id == category_id).first()

    def update(self, category_id: int, category: CategoryUpdate) -> Optional[Category]:
        """Update a category"""
        db_category = self.get_by_id(category_id)
        if not db_category:
            return None

        # Check if new name already exists
        if category.name and category.name != db_category.name:
            if self.repository.get_by_name(category.name):
                raise ValidationException("Category name already exists")

        # Update category fields
        update_data = category.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_category, field, value)

        self.db.commit()
        self.db.refresh(db_category)
        return db_category

    def delete(self, category_id: int) -> bool:
        """Delete a category"""
        db_category = self.get_by_id(category_id)
        if not db_category:
            return False

        self.db.delete(db_category)
        self.db.commit()
        return True

    async def get_by_name(self, name: str) -> Optional[Category]:
        """Get category by name"""
        return await self.repository.get_by_name(name)

    async def search_categories(self, search_term: str) -> List[Category]:
        """Search categories by name or description"""
        return await self.repository.search_categories(search_term)

    def _map_dto_to_entity(self, dto: CategoryCreate | CategoryUpdate) -> Category:
        """Map DTO to Category entity"""
        if isinstance(dto, CategoryCreate):
            return Category(
                name=dto.name,
                description=dto.description
            )
        else:
            return Category(**dto.dict(exclude_unset=True))
