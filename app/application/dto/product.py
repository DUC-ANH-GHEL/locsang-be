from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ProductImageBase(BaseModel):
    url: str
    is_primary: bool = False
    alt_text: Optional[str] = None
    sort_order: int = 0


class ProductImageCreate(ProductImageBase):
    product_id: int


class ProductImageUpdate(BaseModel):
    url: Optional[str] = None
    is_primary: Optional[bool] = None
    alt_text: Optional[str] = None
    sort_order: Optional[int] = None


class ProductImageResponse(ProductImageBase):
    id: int
    product_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductVariantBase(BaseModel):
    sku: str
    size: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = None
    stock: int = 0
    is_active: bool = True


class ProductVariantCreate(ProductVariantBase):
    pass


class ProductVariantUpdate(BaseModel):
    sku: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = None
    stock: Optional[int] = None
    is_active: Optional[bool] = None


class ProductVariantResponse(ProductVariantBase):
    id: int
    product_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    # Identity
    name: str
    slug: str
    sku: str

    # Content
    description: Optional[str] = None

    # Pricing / inventory
    price: float
    sale_price: Optional[float] = None
    currency: str = "VND"
    stock: int = 0

    # Shipping dimensions
    weight: float
    length: float
    width: float
    height: float

    # Category + status
    category_id: int
    is_active: bool = True

    # Optional storefront product attributes
    affiliate: Optional[int] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    pet_type: Optional[str] = None
    season: Optional[str] = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = None
    currency: Optional[str] = None
    stock: Optional[int] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    category_id: Optional[int] = None
    is_active: Optional[bool] = None
    affiliate: Optional[int] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    pet_type: Optional[str] = None
    season: Optional[str] = None


class ProductResponse(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime
    images: List[ProductImageResponse] = Field(default_factory=list)
    variants: List[ProductVariantResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


# Backwards-compatible DTOs used elsewhere (kept intentionally)
class ProductOut(BaseModel):
    id: int
    name: str
    sku: str
    description: Optional[str] = None
    price: float
    affiliate: Optional[int] = None
    weight: float
    length: float
    width: float
    height: float
    is_active: bool
    category_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductList(ProductOut):
    image: Optional[str] = ""
