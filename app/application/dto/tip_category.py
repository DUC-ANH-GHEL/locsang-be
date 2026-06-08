from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TipCategoryCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


class TipCategoryUpdateBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    slug: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class TipCategoryItem(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TipCategoryListResponse(BaseModel):
    success: bool = True
    data: List[TipCategoryItem]


class TipCategoryDetailResponse(BaseModel):
    success: bool = True
    data: TipCategoryItem
