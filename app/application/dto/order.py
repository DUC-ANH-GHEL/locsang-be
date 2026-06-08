from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, conint

class OrderItemBase(BaseModel):
    product_id: int
    quantity: conint(gt=0)
    price: float

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemUpdate(BaseModel):
    quantity: Optional[conint(gt=0)] = None
    price: Optional[float] = None

class OrderItemResponse(OrderItemBase):
    id: int
    order_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class OrderBase(BaseModel):
    customer_id: int
    shipping_address: str
    shipping_phone: str
    shipping_name: str
    note: Optional[str] = None

class OrderCreate(OrderBase):
    items: List[OrderItemCreate]

class OrderUpdate(BaseModel):
    shipping_address: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_name: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None

class OrderResponse(OrderBase):
    id: int
    status: str
    total_amount: float
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True

class ShippingInfoCreate(BaseModel):
    recipient_name: str
    recipient_phone: str
    address: str
    province: str
    district: str
    ward: str

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    # shipping_info: ShippingInfoCreate
    payment_method: str
    note: Optional[str] = None
    receiver_name: str
    receiver_phone: str
    receiver_address: str
    receiver_province_id: int
    receiver_district_id: int
    receiver_ward_id: int
