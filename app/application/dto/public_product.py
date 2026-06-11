from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    size: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    compare_price: Optional[float] = Field(default=None, alias="comparePrice")
    cost_price: Optional[float] = Field(default=None, alias="costPrice")
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
    weight_gram: Optional[float] = Field(default=None, alias="weightGram")
    dimension_text: Optional[str] = Field(default=None, alias="dimensionText")

    model_config = ConfigDict(populate_by_name=True)


class ProductComboItem(BaseModel):
    label: str
    quantity: int = 1
    local_product_id: Optional[str] = Field(default=None, alias="localProductId")
    local_product_slug: Optional[str] = Field(default=None, alias="localProductSlug")
    image: Optional[str] = None
    price: Optional[float] = None
    required: bool = False

    model_config = ConfigDict(populate_by_name=True)


class ProductComboOffer(BaseModel):
    title: str
    description: Optional[str] = None
    items: List[ProductComboItem] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ProductPromotionItem(BaseModel):
    label: str
    quantity: int = 1
    local_product_id: Optional[str] = Field(default=None, alias="localProductId")
    local_product_slug: Optional[str] = Field(default=None, alias="localProductSlug")
    image: Optional[str] = None
    price: Optional[float] = None

    model_config = ConfigDict(populate_by_name=True)


class ProductPromotionOffer(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    promotion_type: Optional[str] = Field(default=None, alias="promotionType")
    promotion_kind: Optional[str] = Field(default=None, alias="promotionKind")
    starts_at: Optional[str] = Field(default=None, alias="startsAt")
    ends_at: Optional[str] = Field(default=None, alias="endsAt")
    meta: dict[str, Any] = Field(default_factory=dict)
    items: List[ProductPromotionItem] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ProductReviewItem(BaseModel):
    id: str
    reviewer_name: str = Field(alias="reviewerName")
    rating: int
    comment: Optional[str] = None
    is_verified_purchase: bool = Field(default=False, alias="isVerifiedPurchase")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class ProductReviewSummary(BaseModel):
    average: float = 0.0
    count: int = 0
    breakdown: dict[str, int] = Field(default_factory=dict)


class ProductReviewsResponse(BaseModel):
    success: bool = True
    data: List[ProductReviewItem]
    summary: ProductReviewSummary


class CreateProductReviewBody(BaseModel):
    reviewer_name: str = Field(alias="reviewerName", min_length=1, max_length=100)
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)
    tracking_code: str = Field(alias="trackingCode", min_length=4, max_length=100)
    phone: str = Field(min_length=8, max_length=20)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator('phone')
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        phone = ''.join(ch for ch in value if ch.isdigit() or ch == '+')
        if len(phone) < 8:
            raise ValueError('phone is invalid')
        return phone


class PublicProductItem(BaseModel):
    id: str
    name: str
    slug: str
    price: float
    original_price: Optional[float] = Field(default=None, alias="originalPrice")
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    thumbnail: Optional[str] = None
    stock: int
    allow_backorder: bool = Field(default=False, alias="allowBackorder")
    can_purchase: bool = Field(default=False, alias="canPurchase")
    stock_status: str = Field(default="out", alias="stockStatus")
    status: ProductStatus
    category: CategoryRef
    rating_summary: ProductReviewSummary = Field(default_factory=ProductReviewSummary, alias="ratingSummary")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class PublicProductDetail(PublicProductItem):
    short_description: Optional[str] = Field(default=None, alias="shortDescription")
    description: Optional[str] = None
    currency: Optional[str] = None
    sale_price: Optional[float] = Field(default=None, alias="salePrice")
    sku: Optional[str] = None
    affiliate: Optional[int] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    pet_type: Optional[str] = Field(default=None, alias="petType")
    season: Optional[str] = None
    weight: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    has_variants: bool = Field(default=False, alias="hasVariants")
    featured: bool = False
    tags: List[str] = Field(default_factory=list)
    specifications: List[ProductSpecificationItem] = Field(default_factory=list)
    images: List[ProductImageItem] = Field(default_factory=list)
    variants: List[ProductVariantItem] = Field(default_factory=list)
    combo_offers: List[ProductComboOffer] = Field(default_factory=list, alias="comboOffers")
    promotion_offers: List[ProductPromotionOffer] = Field(default_factory=list, alias="promotionOffers")
    rating_summary: ProductReviewSummary = Field(default_factory=ProductReviewSummary, alias="ratingSummary")
    reviews: List[ProductReviewItem] = Field(default_factory=list)

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
    original_price: Optional[float] = Field(default=None, alias="originalPrice")
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
    original_price: Optional[float] = Field(default=None, alias="originalPrice")
    category_id: Optional[str] = Field(default=None, alias="categoryId")
    stock: Optional[int] = None
    status: Optional[ProductStatus] = None
    thumbnail: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)
