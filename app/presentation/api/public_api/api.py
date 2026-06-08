from fastapi import APIRouter

from app.presentation.api.public_api.endpoints.accounts import router as accounts_router
from app.presentation.api.public_api.endpoints.contacts import router as contacts_router
from app.presentation.api.public_api.endpoints.customer_stories import router as customer_stories_router
from app.presentation.api.public_api.endpoints.home_content import router as home_content_router
from app.presentation.api.public_api.endpoints.orders import router as orders_router
from app.presentation.api.public_api.endpoints.products import router as products_router
from app.presentation.api.public_api.endpoints.tips import router as tips_router

public_api_router = APIRouter()
public_api_router.include_router(accounts_router)
public_api_router.include_router(home_content_router)
public_api_router.include_router(customer_stories_router)
public_api_router.include_router(products_router)
public_api_router.include_router(orders_router)
public_api_router.include_router(tips_router)
public_api_router.include_router(contacts_router)
