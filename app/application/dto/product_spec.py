from pydantic import BaseModel

class ProductSpecBase(BaseModel):
    product_id: int
    label: str
    value: str

class ProductSpecCreate(ProductSpecBase):
    pass

class ProductSpecOut(ProductSpecBase):
    id: int
    class Config:
        orm_mode = True
