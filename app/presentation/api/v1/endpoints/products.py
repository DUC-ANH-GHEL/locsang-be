from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Form, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.core.deps import get_current_user, get_db
from app.domain.models.user import User
from app.application.dto.product import ProductCreate, ProductUpdate, ProductResponse, ProductImageCreate, ProductImageUpdate, ProductImageResponse
from app.application.dto.product import ProductVariantCreate
from app.application.services.product_service import ProductService
from app.infrastructure.repositories.product_repository import ProductRepository
from app.core.exceptions import NotFoundException, ValidationException

router = APIRouter()

def get_product_service(db: AsyncSession = Depends(get_db)) -> ProductService:
    """Get product service instance"""
    repository = ProductRepository(db)
    return ProductService(repository)

@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    name: str = Form(...),
    slug: str = Form(...),
    description: Optional[str] = Form(None),
    price: float = Form(...),
    sale_price: Optional[float] = Form(None),
    currency: str = Form("VND"),
    sku: str = Form(...),
    affiliate: int = Form(0),
    stock: int = Form(0),
    brand: Optional[str] = Form(None),
    material: Optional[str] = Form(None),
    size: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    pet_type: Optional[str] = Form(None),
    season: Optional[str] = Form(None),
    weight: float = Form(...),
    length: float = Form(...),
    width: float = Form(...),
    height: float = Form(...),
    is_active: bool = Form(True),
    category_id: int = Form(...),
    variants: Optional[str] = Form(None, description="JSON array of variants"),
    images: Optional[List[UploadFile]] = File(None),
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Create new product"""
    try:
        # Create product DTO
        product_in = ProductCreate(
            name=name,
            slug=slug,
            description=description,
            price=price,
            sale_price=sale_price,
            currency=currency,
            sku=sku,
            affiliate=affiliate,
            stock=stock,
            brand=brand,
            material=material,
            size=size,
            color=color,
            pet_type=pet_type,
            season=season,
            weight=weight,
            length=length,
            width=width,
            height=height,
            is_active=is_active,
            category_id=category_id,
        )

        parsed_variants: list[ProductVariantCreate] = []
        if variants:
            try:
                raw = json.loads(variants)
                if not isinstance(raw, list):
                    raise ValueError("variants must be a JSON array")
                parsed_variants = [ProductVariantCreate(**item) for item in raw]
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid variants JSON: {str(e)}",
                )

        # Create product
        product = await product_service.create(
            product_in,
            images=images or [],
            variants=parsed_variants,
        )
        return product
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug hoặc SKU sản phẩm đã tồn tại. Vui lòng nhập giá trị khác.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/", response_model=List[ProductResponse])
async def get_products(
    skip: int = 0,
    limit: int = 100,
    in_stock: bool = False,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Get all products"""
    if in_stock:
        products = await product_service.get_products_in_stock()
    else:
        products = await product_service.get_active_products()

    return products[skip : skip + limit]

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Get product by ID"""
    try:
        product = await product_service.get_by_id(product_id)
        return product
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.get("/sku/{sku}", response_model=ProductResponse)
async def get_product_by_sku(
    sku: str,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Get product by SKU"""
    product = await product_service.get_by_sku(sku)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    return product

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_in: ProductUpdate,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Update product"""
    try:
        product = await product_service.update(product_id, product_in)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        return product
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug hoặc SKU sản phẩm đã tồn tại. Vui lòng nhập giá trị khác.",
        )

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Delete product"""
    try:
        success = await product_service.delete(product_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.patch("/{product_id}/stock", response_model=ProductResponse)
async def update_product_stock(
    product_id: int,
    quantity: int = Query(..., description="Quantity to add (positive) or remove (negative) from stock"),
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Update product stock"""
    try:
        product = await product_service.update_stock(product_id, quantity)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        return product
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# Product Image endpoints
@router.get("/{product_id}/images", response_model=List[ProductImageResponse])
async def get_product_images(
    product_id: int,
    product_service: ProductService = Depends(get_product_service)
):
    """Get all images for a product"""
    return await product_service.get_product_images(product_id)

@router.post("/{product_id}/images", response_model=ProductImageResponse)
async def add_product_image(
    product_id: int,
    image: ProductImageCreate,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Add a new image to a product"""
    if image.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product ID in path does not match product_id in request body"
        )
    try:
        return await product_service.add_product_image(image)
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.put("/images/{image_id}", response_model=ProductImageResponse)
async def update_product_image(
    image_id: int,
    image: ProductImageUpdate,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Update a product image"""
    try:
        updated_image = await product_service.update_product_image(image_id, image)
        if not updated_image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found"
            )
        return updated_image
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_image(
    image_id: int,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Delete a product image"""
    if not await product_service.delete_product_image(image_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

@router.post("/{product_id}/images/{image_id}/primary", status_code=status.HTTP_204_NO_CONTENT)
async def set_primary_image(
    product_id: int,
    image_id: int,
    product_service: ProductService = Depends(get_product_service),
    current_user: User = Depends(get_current_user)
):
    """Set an image as the primary image for a product"""
    try:
        await product_service.set_primary_image(product_id, image_id)
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
