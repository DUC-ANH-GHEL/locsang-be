from fastapi import APIRouter

from app.presentation.api.admin.endpoints.contacts import router as admin_contacts_router
from app.presentation.api.admin.endpoints.customer_stories import router as admin_customer_stories_router
from app.presentation.api.admin.endpoints.home_content import router as admin_home_content_router
from app.presentation.api.admin.endpoints.notifications import router as admin_notifications_router
from app.presentation.api.admin.endpoints.orders import router as admin_orders_router
from app.presentation.api.admin.endpoints.products import router as admin_products_router
from app.presentation.api.admin.endpoints.accounts import router as admin_accounts_router
from app.presentation.api.admin.endpoints.tip_categories import router as admin_tip_categories_router
from app.presentation.api.admin.endpoints.tips import router as admin_tips_router


admin_api_router = APIRouter()
admin_api_router.include_router(admin_accounts_router)
admin_api_router.include_router(admin_products_router, prefix="/products", tags=["admin-products"])
admin_api_router.include_router(admin_orders_router, prefix="/orders", tags=["admin-orders"])
admin_api_router.include_router(admin_notifications_router)
admin_api_router.include_router(admin_contacts_router, prefix="/contacts", tags=["admin-contacts"])
admin_api_router.include_router(admin_home_content_router, tags=["admin-home-content"])
admin_api_router.include_router(admin_customer_stories_router)
admin_api_router.include_router(admin_tip_categories_router)
admin_api_router.include_router(admin_tips_router)
