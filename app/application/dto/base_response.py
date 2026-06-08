# app/schemas/base_response.py

from pydantic import BaseModel
from typing import Generic, TypeVar, Optional
from pydantic.generics import GenericModel

T = TypeVar("T")

class BaseResponse(GenericModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None
