# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from app.api.v1.endpoints import sample
# from app.core.config import settings
# from app.api.v1.api import api_router

# # app = FastAPI(title=settings.PROJECT_NAME, version="1.0.0")
# app = FastAPI()
# app.include_router(api_router)

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"], allow_credentials=True,
#     allow_methods=["*"], allow_headers=["*"],
# )

# # app.include_router(sample.router, prefix="/api/v1", tags=["Sample"])
# # app.include_router(api_router)


#version 2

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse
from app.core.config import settings
from app.presentation.api.v1.api import api_router
from app.presentation.api.admin.api import admin_api_router
from app.presentation.api.public_api.api import public_api_router
from app.core.deps import oauth2_scheme
from app.core.admin_api_error import AdminAPIError

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API cho hệ thống thương mại điện tử Lộc Sang"
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(admin_api_router, prefix=f"{settings.API_V1_STR}/admin")
app.include_router(admin_api_router, prefix="/api/admin")
app.include_router(admin_api_router, prefix="/admin")
app.include_router(public_api_router, prefix="/api")

# OpenAPI configuration
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", [{"OAuth2PasswordBearer": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


@app.exception_handler(AdminAPIError)
async def admin_api_error_handler(request, exc: AdminAPIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error_code": exc.error_code, "message": exc.message},
    )


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = "\n".join([
        "User-agent: facebookexternalhit",
        "Allow: /",
        "",
        "User-agent: Facebot",
        "Allow: /",
        "",
        "User-agent: *",
        "Allow: /",
    ])
    return PlainTextResponse(content=content)

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=False)
#
