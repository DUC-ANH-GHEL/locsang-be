from typing import Any, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.domain.models.product import Product, ProductImage, ProductVariant

class ProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.model = Product

    async def get_all(self) -> List[Product]:
        """Get all products"""
        result = await self.session.execute(
            select(Product).options(
                selectinload(Product.images),
                selectinload(Product.variants),
            )
        )
        return result.scalars().all()

    async def get_by_id(self, id: int) -> Optional[Product]:
        """Get product by ID"""
        result = await self.session.execute(
            select(Product).where(Product.id == id)
            .options(
                selectinload(Product.images),
                selectinload(Product.variants),
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def create(self, obj_in: Product) -> Product:
        """Create new product"""
        try:
            self.session.add(obj_in)
            await self.session.commit()
            await self.session.refresh(obj_in)
            return obj_in
        except Exception:
            await self.session.rollback()
            raise

    async def update(self, id: int, obj_in: Any) -> Optional[Product]:
        """Update product"""
        result = await self.session.execute(
            select(Product).where(Product.id == id)
        )
        product = result.scalar_one_or_none()
        if not product:
            return None

        if hasattr(obj_in, "model_dump"):
            update_data = obj_in.model_dump(exclude_unset=True)
        elif hasattr(obj_in, "dict"):
            update_data = obj_in.dict(exclude_unset=True)
        else:
            update_data = {k: v for k, v in vars(obj_in).items() if not k.startswith("_")}

        for field, value in update_data.items():
            if hasattr(product, field):
                setattr(product, field, value)

        try:
            await self.session.commit()
            await self.session.refresh(product)
            return product
        except Exception:
            await self.session.rollback()
            raise

    async def delete(self, id: int) -> bool:
        """Delete product"""
        result = await self.session.execute(
            select(Product).where(Product.id == id)
        )
        product = result.scalar_one_or_none()
        if not product:
            return False

        try:
            await self.session.delete(product)
            await self.session.commit()
            return True
        except Exception:
            await self.session.rollback()
            raise

    async def exists(self, id: int) -> bool:
        """Check if product exists"""
        result = await self.session.execute(
            select(Product).where(Product.id == id)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_sku(self, sku: str) -> Optional[Product]:
        """Get product by SKU"""
        result = await self.session.execute(
            select(Product)
            .where(Product.sku == sku)
            .options(
                selectinload(Product.images),
                selectinload(Product.variants),
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_active_products(self) -> List[Product]:
        """Get all active products"""
        result = await self.session.execute(
            select(Product)
            .where(Product.is_active == True)
            .options(
                selectinload(Product.images),
                selectinload(Product.variants),
            )
        )
        return result.scalars().all()

    async def get_products_by_category(self, category_id: int) -> List[Product]:
        """Get products by category"""
        result = await self.session.execute(
            select(Product)
            .where(Product.category_id == category_id)
            .options(
                selectinload(Product.images),
                selectinload(Product.variants),
            )
        )
        return result.scalars().all()

    async def search_products(self, search_term: str) -> List[Product]:
        """Search products by name or description"""
        query = select(Product).where(
            (Product.name.ilike(f"%{search_term}%")) |
            (Product.description.ilike(f"%{search_term}%"))
        ).options(
            selectinload(Product.images),
            selectinload(Product.variants),
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_products_in_stock(self) -> List[Product]:
        """Get products that are in stock"""
        query = select(Product).where(Product.stock > 0).options(
            selectinload(Product.images),
            selectinload(Product.variants),
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_stock(self, product_id: int, quantity: int) -> Optional[Product]:
        """Update product stock"""
        product = await self.get_by_id(product_id)
        if not product:
            return None

        product.stock += quantity
        try:
            await self.session.commit()
            await self.session.refresh(product)
            return product
        except Exception:
            await self.session.rollback()
            raise

    async def get_product_images(self, product_id: int) -> List[ProductImage]:
        """Get all images for a product"""
        result = await self.session.execute(
            select(ProductImage).where(ProductImage.product_id == product_id)
        )
        return result.scalars().all()

    async def get_image_by_id(self, image_id: int) -> Optional[ProductImage]:
        result = await self.session.execute(select(ProductImage).where(ProductImage.id == image_id))
        return result.scalar_one_or_none()

    async def add_variant(self, variant: ProductVariant) -> ProductVariant:
        try:
            self.session.add(variant)
            await self.session.commit()
            await self.session.refresh(variant)
            return variant
        except Exception:
            await self.session.rollback()
            raise

    async def get_variants(self, product_id: int) -> List[ProductVariant]:
        result = await self.session.execute(select(ProductVariant).where(ProductVariant.product_id == product_id))
        return list(result.scalars().all())

    async def add_product_image(self, image: ProductImage) -> ProductImage:
        """Add a new image to a product"""
        try:
            self.session.add(image)
            await self.session.commit()
            await self.session.refresh(image)
            return image
        except Exception:
            await self.session.rollback()
            raise

    async def update_product_image(self, image_id: int, image: ProductImage) -> Optional[ProductImage]:
        """Update a product image"""
        result = await self.session.execute(
            select(ProductImage).where(ProductImage.id == image_id)
        )
        existing_image = result.scalar_one_or_none()
        if not existing_image:
            return None

        if hasattr(image, "model_dump"):
            update_data = image.model_dump(exclude_unset=True)
        elif hasattr(image, "dict"):
            update_data = image.dict(exclude_unset=True)
        else:
            update_data = {k: v for k, v in vars(image).items() if not k.startswith("_")}

        for field, value in update_data.items():
            if hasattr(existing_image, field):
                setattr(existing_image, field, value)

        try:
            await self.session.commit()
            await self.session.refresh(existing_image)
            return existing_image
        except Exception:
            await self.session.rollback()
            raise

    async def delete_product_image(self, image_id: int) -> bool:
        """Delete a product image"""
        try:
            result = await self.session.execute(
                delete(ProductImage).where(ProductImage.id == image_id)
            )
            await self.session.commit()
            return (result.rowcount or 0) > 0
        except Exception:
            await self.session.rollback()
            raise

    async def set_primary_image(self, product_id: int, image_id: int) -> None:
        """Set an image as the primary image for a product"""
        # First, unset any existing primary image
        await self.session.execute(
            update(ProductImage)
            .where(ProductImage.product_id == product_id)
            .values(is_primary=False)
        )
        # Then set the new primary image
        await self.session.execute(
            update(ProductImage)
            .where(ProductImage.id == image_id)
            .values(is_primary=True)
        )
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
