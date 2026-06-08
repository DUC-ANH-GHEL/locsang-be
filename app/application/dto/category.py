from datetime import datetime
from typing import Optional
from pydantic import BaseModel, constr

class CategoryBase(BaseModel):
    name: constr(min_length=1, max_length=100)
    description: Optional[str] = None
    image: Optional[str] = None
    is_active: bool = True

class CategoryCreate(CategoryBase):
    pass

class CategoryUpdate(BaseModel):
    name: Optional[constr(min_length=1, max_length=100)] = None
    description: Optional[str] = None
    image: Optional[str] = None
    is_active: Optional[bool] = None

class CategoryResponse(CategoryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
