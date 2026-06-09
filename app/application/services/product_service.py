from typing import List, Optional

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from app.domain.models.product import Product, ProductImage, ProductVariant
from app.infrastructure.repositories.product_repository import ProductRepository
from app.application.services.base import BaseServiceImpl
from app.application.dto.product import (
    ProductCreate,
    ProductUpdate,
    ProductImageCreate,
    ProductImageUpdate,
    ProductImageResponse,
    ProductVariantCreate,
)
from app.core.exceptions import ValidationException, NotFoundException

class ProductService(BaseServiceImpl[Product, ProductCreate, ProductUpdate]):
    """Product service implementation"""

    def __init__(self, repository: ProductRepository):
        super().__init__(repository)
        self.repository = repository

    async def create(
        self,
        product_in: ProductCreate,
        images: Optional[List[UploadFile]] = None,
        variants: Optional[List[ProductVariantCreate]] = None,
    ) -> Product:
        """Create new product"""
        # Check if SKU already exists
        existing_product = await self.repository.get_by_sku(product_in.sku)
        if existing_product:
            raise ValidationException(f"Product with SKU {product_in.sku} already exists")

        unique_slug = await self.repository.make_unique_slug(product_in.slug)
        if unique_slug != product_in.slug:
            product_in = product_in.model_copy(update={"slug": unique_slug})

        if product_in.sale_price is not None and product_in.sale_price > product_in.price:
            raise ValidationException("sale_price must be <= price")

        if product_in.stock < 0:
            raise ValidationException("stock must be >= 0")

        variants = variants or []
        if variants:
            seen = set()
            total_stock = 0
            for v in variants:
                if not v.sku:
                    raise ValidationException("variant.sku is required")
                if v.sku in seen:
                    raise ValidationException(f"Duplicate variant sku: {v.sku}")
                seen.add(v.sku)

                price = v.price if v.price is not None else product_in.price
                sale_price = v.sale_price
                if sale_price is not None and sale_price > price:
                    raise ValidationException(f"variant.sale_price must be <= price for sku {v.sku}")
                if v.stock < 0:
                    raise ValidationException(f"variant.stock must be >= 0 for sku {v.sku}")
                total_stock += v.stock

            existing_variant_skus = await self.repository.get_variant_skus_in_use(list(seen))
            if existing_variant_skus:
                raise ValidationException(f"Variant SKU already exists: {existing_variant_skus[0]}")

            # When variants exist, keep product.stock as total for convenience
            product_in = product_in.model_copy(update={"stock": total_stock})

        # Create product
        product = Product(**product_in.model_dump())
        try:
            product = await self.repository.create(product)
        except IntegrityError as exc:
            message = str(getattr(exc, "orig", exc)).lower()
            if "products_slug" in message or "ix_products_slug" in message or "slug" in message:
                raise ValidationException("Slug sản phẩm đã tồn tại. Vui lòng thử lại với tên khác.")
            if "products_sku" in message or "ix_products_sku" in message or "sku" in message:
                raise ValidationException("SKU sản phẩm đã tồn tại. Vui lòng nhập SKU khác.")
            raise ValidationException("Dữ liệu sản phẩm bị trùng. Vui lòng kiểm tra lại.")

        # Create variants if any
        if variants:
            for v in variants:
                variant = ProductVariant(
                    product_id=product.id,
                    sku=v.sku,
                    size=v.size,
                    color=v.color,
                    material=v.material,
                    price=(v.price if v.price is not None else product.price),
                    sale_price=v.sale_price,
                    stock=v.stock,
                    is_active=v.is_active,
                )
                await self.repository.add_variant(variant)

        # Upload images if any
        if images:
            cfg = cloudinary.config()
            if not getattr(cfg, "api_key", None) or not getattr(cfg, "cloud_name", None):
                raise ValidationException(
                    "Cloudinary is not configured. Set CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME/CLOUDINARY_API_KEY/CLOUDINARY_API_SECRET."
                )
            for idx, image_file in enumerate(images):
                try:
                    # Upload to Cloudinary
                    result = cloudinary.uploader.upload(
                        image_file.file,
                        folder="products",
                        resource_type="auto"
                    )

                    # Create product image
                    image = ProductImage(
                        product_id=product.id,
                        url=result['secure_url'],
                        public_id=result['public_id'],
                        is_primary=(idx == 0),
                        sort_order=idx,
                    )
                    await self.repository.add_product_image(image)
                except Exception as e:
                    raise ValidationException(f"Error uploading image: {str(e)}")

        # Ensure relationships (images/variants) are loaded for response serialization
        reloaded = await self.repository.get_by_id(product.id)
        return reloaded or product

    async def get_by_id(self, product_id: int) -> Optional[Product]:
        """Get product by ID"""
        product = await self.repository.get_by_id(product_id)
        if not product:
            raise NotFoundException(f"Product with ID {product_id} not found")
        return product

    async def get_by_sku(self, sku: str) -> Optional[Product]:
        """Get product by SKU"""
        return await self.repository.get_by_sku(sku)

    async def get_active_products(self) -> List[Product]:
        """Get all active products"""
        return await self.repository.get_active_products()

    async def get_products_by_category(self, category_id: int) -> List[Product]:
        """Get products by category"""
        return await self.repository.get_products_by_category(category_id)

    async def update(self, product_id: int, product_in: ProductUpdate) -> Optional[Product]:
        """Update product"""
        product = await self.repository.get_by_id(product_id)
        if not product:
            raise NotFoundException(f"Product with ID {product_id} not found")

        # Update product
        updated_product = await self.repository.update(product_id, product_in)
        return updated_product

    async def update_stock(self, product_id: int, quantity: int) -> Optional[Product]:
        """Update product stock"""
        product = await self.repository.get_by_id(product_id)
        if not product:
            raise NotFoundException(f"Product with ID {product_id} not found")

        new_stock = product.stock + quantity
        if new_stock < 0:
            raise ValidationException("Stock cannot be negative")

        return await self.repository.update_stock(product_id, quantity)

    async def get_product_images(self, product_id: int) -> List[ProductImage]:
        """Get all images for a product"""
        return await self.repository.get_product_images(product_id)

    async def add_product_image(self, image: ProductImageCreate) -> ProductImage:
        """Add a new image to a product (expects a URL)."""
        product = await self.repository.get_by_id(image.product_id)
        if not product:
            raise ValidationException(f"Product with ID {image.product_id} not found")

        product_image = ProductImage(
            product_id=image.product_id,
            url=image.url,
            is_primary=image.is_primary,
            alt_text=image.alt_text,
            sort_order=image.sort_order,
        )
        return await self.repository.add_product_image(product_image)

    async def update_product_image(self, image_id: int, image: ProductImageUpdate) -> Optional[ProductImage]:
        """Update a product image"""
        return await self.repository.update_product_image(image_id, image)

    def _map_dto_to_entity(self, dto: ProductCreate | ProductUpdate) -> Product:
        """Map DTO to Product entity"""
        if isinstance(dto, ProductCreate):
            return Product(
                name=dto.name,
                description=dto.description,
                price=dto.price,
                stock=dto.stock,
                sku=dto.sku,
                is_active=dto.is_active,
                category_id=dto.category_id
            )
        else:
            return Product(**dto.dict(exclude_unset=True))

    async def search_products(self, search_term: str) -> List[Product]:
        """Search products by name or description"""
        return await self.repository.search_products(search_term)

    async def get_products_in_stock(self) -> List[Product]:
        """Get products that are in stock"""
        return await self.repository.get_products_in_stock()

    async def delete_product_image(self, image_id: int) -> bool:
        """Delete a product image"""
        return await self.repository.delete_product_image(image_id)

    async def set_primary_image(self, product_id: int, image_id: int) -> None:
        """Set an image as the primary image for a product"""
        product = await self.repository.get_by_id(product_id)
        if not product:
            raise ValidationException(f"Product with ID {product_id} not found")

        image = await self.repository.get_image_by_id(image_id)
        if not image:
            raise ValidationException(f"Image with ID {image_id} not found")
        if image.product_id != product_id:
            raise ValidationException("Image does not belong to this product")

        await self.repository.set_primary_image(product_id, image_id)
