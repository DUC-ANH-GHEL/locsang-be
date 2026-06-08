from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class PublicOrderItemCreate(BaseModel):
    product_id: int = Field(alias='productId', gt=0)
    product_variant_id: Optional[int] = Field(default=None, alias='productVariantId', gt=0)
    quantity: int = Field(gt=0)

    model_config = ConfigDict(populate_by_name=True)


class PublicOrderCreateBody(BaseModel):
    receiver_name: str = Field(alias='receiverName', min_length=1, max_length=120)
    receiver_phone: str = Field(alias='receiverPhone', min_length=8, max_length=20)
    receiver_email: Optional[EmailStr] = Field(default=None, alias='receiverEmail')
    receiver_address: str = Field(alias='receiverAddress', min_length=3, max_length=300)
    receiver_province_id: Optional[int] = Field(default=None, alias='receiverProvinceId', gt=0)
    receiver_district_id: Optional[int] = Field(default=None, alias='receiverDistrictId', gt=0)
    receiver_ward_id: Optional[int] = Field(default=None, alias='receiverWardId', gt=0)
    receiver_province_name: Optional[str] = Field(default=None, alias='receiverProvinceName', max_length=120)
    receiver_district_name: Optional[str] = Field(default=None, alias='receiverDistrictName', max_length=120)
    receiver_ward_name: Optional[str] = Field(default=None, alias='receiverWardName', max_length=120)
    payment_method: str = Field(alias='paymentMethod', default='cod', min_length=2, max_length=50)
    note: Optional[str] = Field(default=None, max_length=2000)
    items: List[PublicOrderItemCreate] = Field(min_length=1)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator('receiver_phone')
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        phone = ''.join(ch for ch in value if ch.isdigit() or ch == '+')
        if len(phone) < 8:
            raise ValueError('receiverPhone is invalid')
        return phone


class PublicOrderItemResponse(BaseModel):
    product_id: int = Field(alias='productId')
    product_variant_id: Optional[int] = Field(default=None, alias='productVariantId')
    name: str
    sku: Optional[str] = None
    quantity: int
    unit_price: float = Field(alias='unitPrice')
    subtotal: float

    model_config = ConfigDict(populate_by_name=True)


class PublicOrderResponseData(BaseModel):
    id: int
    tracking_code: Optional[str] = Field(default=None, alias='trackingCode')
    pancake_order_id: Optional[str] = Field(default=None, alias='pancakeOrderId')
    status: str
    payment_status: str = Field(alias='paymentStatus')
    payment_method: str = Field(alias='paymentMethod')
    receiver_name: Optional[str] = Field(default=None, alias='receiverName')
    receiver_phone: Optional[str] = Field(default=None, alias='receiverPhone')
    receiver_address: Optional[str] = Field(default=None, alias='receiverAddress')
    total_amount: float = Field(alias='totalAmount')
    created_at: datetime = Field(alias='createdAt')
    items: List[PublicOrderItemResponse]

    model_config = ConfigDict(populate_by_name=True)


class PublicOrderCreateResponse(BaseModel):
    success: bool = True
    data: PublicOrderResponseData


class PublicOrderLookupResponse(BaseModel):
    success: bool = True
    data: PublicOrderResponseData
