from pydantic import BaseModel

class OrderItemBase(BaseModel):
    order_id: int
    product_id: int
    quantity: int
    price: float

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemOut(OrderItemBase):
    id: int
    class Config:
        orm_mode = True
