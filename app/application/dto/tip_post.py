from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


TipStatus = Literal["draft", "published", "archived"]


class TipPostCreateBody(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    slug: Optional[str] = Field(default=None, max_length=260)
    excerpt: Optional[str] = Field(default=None, max_length=800)
    content: Optional[str] = None
    template_key: Optional[str] = Field(default=None, max_length=80)
    content_blocks: Optional[List[dict]] = None
    featured_image: Optional[str] = Field(default=None, max_length=1200)
    category: Optional[str] = Field(default=None, max_length=120)
    tags: List[str] = Field(default_factory=list)
    status: TipStatus = "draft"
    featured: bool = False
    seo_title: Optional[str] = Field(default=None, max_length=320)
    seo_description: Optional[str] = Field(default=None, max_length=500)
    published_at: Optional[datetime] = None


class TipPostUpdateBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=220)
    slug: Optional[str] = Field(default=None, max_length=260)
    excerpt: Optional[str] = Field(default=None, max_length=800)
    content: Optional[str] = None
    template_key: Optional[str] = Field(default=None, max_length=80)
    content_blocks: Optional[List[dict]] = None
    featured_image: Optional[str] = Field(default=None, max_length=1200)
    category: Optional[str] = Field(default=None, max_length=120)
    tags: Optional[List[str]] = None
    status: Optional[TipStatus] = None
    featured: Optional[bool] = None
    seo_title: Optional[str] = Field(default=None, max_length=320)
    seo_description: Optional[str] = Field(default=None, max_length=500)
    published_at: Optional[datetime] = None


class TipPostItem(BaseModel):
    id: int
    title: str
    slug: str
    excerpt: Optional[str] = None
    content: Optional[str] = None
    template_key: Optional[str] = None
    content_blocks: List[dict] = Field(default_factory=list)
    featured_image: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: TipStatus
    featured: bool = False
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int


class TipListResponse(BaseModel):
    success: bool = True
    data: List[TipPostItem]
    pagination: PaginationMeta


class TipDetailResponse(BaseModel):
    success: bool = True
    data: TipPostItem
