from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CustomerStoryCreateBody(BaseModel):
    customer_name: str = Field(min_length=2, max_length=140)
    pet_name: Optional[str] = Field(default=None, max_length=140)
    customer_title: Optional[str] = Field(default=None, max_length=180)
    quote: str = Field(min_length=5, max_length=4000)
    rating: int = Field(default=5, ge=1, le=5)
    image_url: Optional[str] = Field(default=None, max_length=1200)
    is_featured: bool = False
    is_active: bool = True
    sort_order: int = 0


class CustomerStoryUpdateBody(BaseModel):
    customer_name: Optional[str] = Field(default=None, min_length=2, max_length=140)
    pet_name: Optional[str] = Field(default=None, max_length=140)
    customer_title: Optional[str] = Field(default=None, max_length=180)
    quote: Optional[str] = Field(default=None, min_length=5, max_length=4000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    image_url: Optional[str] = Field(default=None, max_length=1200)
    is_featured: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class CustomerStoryItem(BaseModel):
    id: int
    customer_name: str
    pet_name: Optional[str] = None
    customer_title: Optional[str] = None
    quote: str
    rating: int
    image_url: Optional[str] = None
    is_featured: bool = False
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerStoryListResponse(BaseModel):
    success: bool = True
    data: List[CustomerStoryItem]


class CustomerStoryDetailResponse(BaseModel):
    success: bool = True
    data: CustomerStoryItem
