from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
import cloudinary


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
    )

    PROJECT_NAME: str = "LocSang API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    FRONTEND_BASE_URL: str = "https://locsang.shop"

    # Security
    SECRET_KEY: str = "your-secret-key-here"  # Change this in production
    ALGORITHM: str = "HS256"
    # Keep admin sessions stable by default (7 days) unless overridden by env.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    # Development-friendly default so forgot-password can complete without email service.
    # Set to False in production and send reset links via email.
    AUTH_DEBUG_EXPOSE_PASSWORD_RESET_TOKEN: bool = True

    # Database
    # NOTE: Do not hardcode production credentials in source control.
    # Override this via the DATABASE_URL environment variable or a local .env file.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/locsang"

    # CORS
    BACKEND_CORS_ORIGINS: list = [
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://locsang.shop",
        "https://locsang-fe.vercel.app",
    ]

    # Cloudinary
    CLOUDINARY_URL: Optional[str] = None
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # OAuth (optional)
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    FACEBOOK_APP_ID: Optional[str] = None
    FACEBOOK_APP_SECRET: Optional[str] = None

    # SMTP mail (optional)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: str = "Lộc Sang"

    # Contact mail flow
    CONTACT_NOTIFICATION_TO_EMAIL: Optional[str] = None
    CONTACT_SEND_AUTO_REPLY: bool = True

    # Order mail flow
    ORDER_NOTIFICATION_TO_EMAIL: Optional[str] = None
    ORDER_SEND_AUTO_REPLY: bool = True

settings = Settings()

# Configure Cloudinary
if settings.CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
elif all([
    settings.CLOUDINARY_CLOUD_NAME,
    settings.CLOUDINARY_API_KEY,
    settings.CLOUDINARY_API_SECRET,
]):
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )
