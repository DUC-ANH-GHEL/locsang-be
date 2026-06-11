from fastapi import APIRouter
from app.presentation.api.v1.endpoints.users import router as user_routes
from app.presentation.api.v1.endpoints.categories import router as category_routes
from app.presentation.api.v1.endpoints.orders import router as order_routes
from app.presentation.api.v1.endpoints.gemini import router as gemini_routes

api_router = APIRouter()
api_router.include_router(user_routes)
api_router.include_router(category_routes)
api_router.include_router(order_routes, prefix="/orders", tags=["orders"])
api_router.include_router(gemini_routes, prefix="/gemini", tags=["gemini"])
