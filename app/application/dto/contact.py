from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=8, max_length=20)
    message: str = Field(min_length=1, max_length=4000)
    email: EmailStr | None = None
    subject: str | None = Field(default=None, max_length=200)
    product_id: int | None = None


class ContactOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None = None
    subject: str | None = None
    message: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ContactCreateResponse(BaseModel):
    success: bool = True
    message: str
    data: ContactOut
