from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AdminOrderUpdateBody(BaseModel):
    status: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=2000)
    tracking_code: Optional[str] = Field(default=None, alias='trackingCode', max_length=120)

    class Config:
        populate_by_name = True


class AdminBulkOrdersBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=50)
    status: Optional[str] = Field(default=None)

    class Config:
        populate_by_name = True
