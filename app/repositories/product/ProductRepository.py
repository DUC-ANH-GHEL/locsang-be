from app.domain.models.product import Product, ProductImage, ProductSpec
from app.infrastructure.repositories.base import BaseRepository
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from sqlalchemy import select, update, delete

class ProductRepository(BaseRepository[Product]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Product)

    async def CreateProduct(self, db: AsyncSession, product: Product) -> Product:
        db.add(product)
        await db.flush()
        return product

    async def AddProductImages(self, db: AsyncSession, product_id: int, image_urls: List[str]):
        for idx, url in enumerate(image_urls):
            db.add(ProductImage(
                product_id=product_id,
                image_url=url,
                is_primary=(idx == 0)
            ))

    async def AddProductSpecs(self, db: AsyncSession, product_id: int, specs: List[dict]):
        for spec in specs:
            db.add(ProductSpec(
                product_id=product_id,
                label=spec["key"],
                value=spec["value"]
            ))

productRepository = ProductRepository()
