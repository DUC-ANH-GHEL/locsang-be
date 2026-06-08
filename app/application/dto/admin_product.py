from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ProductStatus = Literal["active", "inactive", "draft", "discontinued"]
MediaType = Literal["image", "video"]


class ShippingDTO(BaseModel):
    weight: float = 0
    length: float = 0
    width: float = 0
    height: float = 0


class MediaItemDTO(BaseModel):
    url: str
    type: MediaType = "image"
    sort_order: int = 0


class AttributeDTO(BaseModel):
    id: Optional[int] = None
    name: str
    values: List[str] = Field(default_factory=list)


class VariantDTO(BaseModel):
    id: Optional[int] = None

    sku: str
    price: float
    compare_price: Optional[float] = None
    cost_price: Optional[float] = None

    stock: int = 0
    manage_stock: bool = True
    allow_backorder: bool = False

    status: ProductStatus = "active"

    attribute_values: Dict[str, str] = Field(default_factory=dict)
    image_url: Optional[str] = None


class AdminProductCreateBody(BaseModel):
    name: str
    slug: str
    seo_slug: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None

    status: ProductStatus = "active"
    featured: bool = False

    category_id: int
    brand: Optional[str] = None
    pet_type: Optional[str] = None
    season: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    has_variants: bool = True

    shipping: ShippingDTO = Field(default_factory=ShippingDTO)
    media: List[MediaItemDTO] = Field(default_factory=list)
    attributes: List[AttributeDTO] = Field(default_factory=list)
    variants: List[VariantDTO] = Field(default_factory=list)


class AdminProductUpdateBody(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    seo_slug: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None

    status: Optional[ProductStatus] = None
    featured: Optional[bool] = None

    category_id: Optional[int] = None
    brand: Optional[str] = None
    pet_type: Optional[str] = None
    season: Optional[str] = None
    tags: Optional[List[str]] = None

    has_variants: Optional[bool] = None

    shipping: Optional[ShippingDTO] = None
    media: Optional[List[MediaItemDTO]] = None
    attributes: Optional[List[AttributeDTO]] = None
    variants: Optional[List[VariantDTO]] = None

    deleted_variant_ids: List[int] = Field(default_factory=list)
    deleted_attribute_ids: List[int] = Field(default_factory=list)


class BulkUpdateVariantsBody(BaseModel):
    variant_ids: List[int]
    update: Dict[str, Any] = Field(default_factory=dict)


class GenerateVariantsBody(BaseModel):
    attributes: List[AttributeDTO] = Field(default_factory=list)


BulkProductAction = Literal["status", "delete", "category", "affiliate"]


class AdminBulkProductsBody(BaseModel):
    ids: List[int]
    action: BulkProductAction
    data: Dict[str, Any] = Field(default_factory=dict)


class AdminVariantPatchBody(BaseModel):
    price: Optional[float] = None
    cost_price: Optional[float] = None
    stock: Optional[int] = None
    status: Optional[ProductStatus] = None


class AdminProductQuickPatchBody(BaseModel):
    price: Optional[float] = None
    cost_price: Optional[float] = None
    stock: Optional[int] = None
    status: Optional[ProductStatus] = None
    featured: Optional[bool] = None
    category_id: Optional[int] = None
    affiliate: Optional[int] = None
