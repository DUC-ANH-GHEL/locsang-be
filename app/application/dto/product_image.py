from pydantic import BaseModel

class ProductImageBase(BaseModel):
    product_id: int
    image_url: str
    is_primary: bool = False

class ProductImageCreate(ProductImageBase):
    pass

class ProductImageOut(ProductImageBase):
    id: int
    class Config:
        orm_mode = True
