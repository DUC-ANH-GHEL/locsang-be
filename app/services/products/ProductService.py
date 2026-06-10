from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.models.product import Product, ProductImage
from typing import List, Optional
import string
from app.infrastructure.repositories.product_repository import ProductRepository
from app.application.services.base import BaseServiceImpl
from app.application.dto.product import (
    ProductCreate,
    ProductUpdate,
    ProductImageCreate,
    ProductImageUpdate,
    ProductImageResponse
)
from app.dto.product_image import ProductImageOut
from app.core.exceptions import ValidationException
from datetime import datetime
from app.cloudinary_config import cloudinary
import re
import json
import traceback

class ProductService(BaseServiceImpl[Product]):
    def __init__(self, repository: ProductRepository):
        super().__init__(repository)
        self.repository = repository

    async def create_product_with_images_and_specs(
            self,
            db: AsyncSession,
            name: str,
            sku: str,
            description: str,
            price: float,
            affiliate: float,
            weight: float,
            length: float,
            width: float,
            height: float,
            category_id: int,
            specs: str,
            images: List
    ):
        product = Product(
            name = name,
            sku = sku,
            description = description,
            price = price,
            affiliate = affiliate,
            weight = weight,
            length = length,
            width = width,
            height = height,
            category_id = category_id
        )
        try:
            product = await self.repository.CreateProduct(self.repository.db, product)
            await self.repository.add_product_image

            # upload anh len Cloudinary
            image_url = []
            for idx, file in enumerate(images):
                upload_result = cloudinary.uploader.upload(file.file, folder = "products")
                image_url.append(upload_result["secure_url"])
                # db.add(ProductImage(
                #     product_id = product.id,
                #     image_url = image_url,
                #     is_primary=(idx == 0)
                # ))
            await self.repository.AddProductImages(self.repository.db, product.id, image_url)

            # them specs
            specs_list = json.loads(specs)
            if specs_list and specs != '[]':
                # for spec in specs_list:
                #     db.add(ProductSpec(
                #         product_id = product.id,
                #         label=spec['key'],
                #         value = spec['value']
                #     ))
                await self.repository.AddProductSpecs(self.repository.db, product.id, specs_list)

            product_id = product.id  # ✅ lưu lại trước khi session đóng
            await self.repository.db.commit()
            return product_id
        except Exception as e:
                # rollback transaction và in traceback
                await self.repository.db.rollback()
                print("🛑 Lỗi khi tạo product:", e)
                traceback.print_exc()
                raise

    async def getProductById(db: AsyncSession, id: int):
        product = await db.execute(select(Product).where(Product.id == id))
        result = product.scalar_one_or_none()
        return result

    async def getProductImageByProductId(db: AsyncSession, productId: int) -> List[ProductImageOut]:
        productImage = await db.execute(select(ProductImage).where(productId == ProductImage.product_id))
        result = productImage.scalars().all()
        return result

    async def updateProduct(db: AsyncSession, product: ProductUpdate):
        productUpdate0 = await db.execute(select(Product).where(Product.id == product.id))
        productUpdate = productUpdate0.scalars().first()
        if productUpdate:
            productUpdate.id= product.id
            productUpdate.name= product.name
            productUpdate.sku= product.sku
            productUpdate.description= product.description
            productUpdate.price= product.price
            productUpdate.weight= product.weight
            productUpdate.length= product.length
            productUpdate.width = product.width
            productUpdate.height = product.height
            productUpdate.affiliate = product.affiliate
            productUpdate.is_active = product.is_active
            productUpdate.category_id = product.category_id
            productUpdate.updated_at = datetime.now()

        if product.listImageNew:
            # upload anh len Cloudinary
            for idx, file in enumerate(product.listImageNew):
                upload_result = cloudinary.uploader.upload(file.file, folder = "products")
                image_url = upload_result["secure_url"]
                db.add(ProductImage(
                    product_id = product.id,
                    image_url = image_url,
                    is_primary=False
                ))

        productImage = await db.execute(select(ProductImage).where(ProductImage.product_id == product.id))
        listImage = productImage.scalars().all()
        image_urls = [img.image_url for img in listImage]
        diff = list(set(image_urls) - set(product.listImageCurrent))
        if diff:
            for url in diff:
                remove_result = cloudinary.uploader.destroy(extract_public_id(url))
                db_remove = next(img for img in listImage if img.image_url == url)
                await db.delete(db_remove)

        await db.commit()
        await db.refresh(productUpdate)



    def extract_public_id(url: str) -> str:
        # Regex lấy phần từ sau '/upload/' đến trước phần mở rộng
        match = re.search(r"products/([^/]+\.(jpg|png|jpeg|webp))$", url)
        if match:
            return match.group(1)
        else:
            raise ValueError("Không thể extract public_id từ URL: " + url)
