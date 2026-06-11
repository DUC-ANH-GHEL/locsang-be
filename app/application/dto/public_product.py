from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ProductStatus = Literal["active", "inactive"]
SortBy = Literal["createdAt", "price", "name"]
SortOrder = Literal["asc", "desc"]


class CategoryRef(BaseModel):
    id: str
    name: str


class ProductImageItem(BaseModel):
    id: str
    url: str
    is_primary: bool = Field(default=False, alias="isPrimary")
    alt_text: Optional[str] = Field(default=None, alias="altText")

    model_config = ConfigDict(populate_by_name=True)


class ProductSpecificationItem(BaseModel):
    label: str
    value: str


class ProductVariantItem(BaseModel):
    id: str
    sku: str
    price: Optional[float] = None
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    stock: int = 0
    manage_stock: bool = Field(default=True, alias="manageStock")
    allow_backorder: bool = Field(default=False, alias="allowBackorder")
    can_purchase: bool = Field(default=False, alias="canPurchase")
    status: str = "active"
    is_active: bool = Field(default=True, alias="isActive")
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    attribute_values: dict[str, str] = Field(default_factory=dict, alias="attributeValues")
    variant_name: Optional[str] = Field(default=None, alias="variantName")
    media_urls: List[str] = Field(default_factory=list, alias="mediaUrls")
    video_urls: List[str] = Field(default_factory=list, alias="videoUrls")

    model_config = ConfigDict(populate_by_name=True)


class PublicProductItem(BaseModel):
    id: str
    name: str
    slug: str
    price: float
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    thumbnail: Optional[str] = None
    stock: int
    allow_backorder: bool = Field(default=False, alias="allowBackorder")
    can_purchase: bool = Field(default=False, alias="canPurchase")
    stock_status: str = Field(default="out", alias="stockStatus")
    status: ProductStatus
    category: CategoryRef
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class PublicProductDetail(PublicProductItem):
    short_description: Optional[str] = Field(default=None, alias="shortDescription")
    description: Optional[str] = None
    currency: Optional[str] = None
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    sku: Optional[str] = None
    brand: Optional[str] = None
    has_variants: bool = Field(default=False, alias="hasVariants")
    featured: bool = False
    tags: List[str] = Field(default_factory=list)
    specifications: List[ProductSpecificationItem] = Field(default_factory=list)
    images: List[ProductImageItem] = Field(default_factory=list)
    variants: List[ProductVariantItem] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class Pagination(BaseModel):
    page: int
    limit: int
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")
    has_next: bool = Field(alias="hasNext")
    has_prev: bool = Field(alias="hasPrev")

    model_config = ConfigDict(populate_by_name=True)


class ListProductsResponse(BaseModel):
    success: bool = True
    data: List[PublicProductItem]
    pagination: Pagination


class ProductDetailResponse(BaseModel):
    success: bool = True
    data: PublicProductDetail


class CreateProductBody(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    category_id: str = Field(alias="categoryId")
    stock: int = 0
    status: ProductStatus = "active"
    thumbnail: Optional[str] = None
    images: List[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class UpdateProductBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    category_id: Optional[str] = Field(default=None, alias="categoryId")
    stock: Optional[int] = None
    status: Optional[ProductStatus] = None
    thumbnail: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)
