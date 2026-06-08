from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, constr

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    is_active: bool = True
    role_id: int

class UserCreate(UserBase):
    password: constr(min_length=8)

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    role_id: Optional[int] = None
    password: Optional[constr(min_length=8)] = None

class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(UserBase):
    id: int
    email: str
    role_id: int
    class Config:
        # orm_mode = True
         from_attributes = True  # ✅ dùng với Pydantic v2
