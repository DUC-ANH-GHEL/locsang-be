from fastapi import APIRouter

from app.presentation.api.public.endpoints.products import router as products_router

public_api_router = APIRouter()
public_api_router.include_router(products_router)
