from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.category import Category
from app.infrastructure.repositories.base import SQLAlchemyRepository
from app.core.exceptions import NotFoundException

class CategoryRepository(SQLAlchemyRepository[Category]):
    """Category repository implementation"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Category)

    async def get_by_name(self, name: str) -> Optional[Category]:
        """Get category by name"""
        query = select(Category).where(Category.name == name)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def search_categories(self, search_term: str) -> List[Category]:
        """Search categories by name or description"""
        query = select(Category).where(
            (Category.name.ilike(f"%{search_term}%")) |
            (Category.description.ilike(f"%{search_term}%"))
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
