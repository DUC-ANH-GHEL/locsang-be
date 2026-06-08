import cloudinary

from app.core.config import settings


if all([
  settings.CLOUDINARY_CLOUD_NAME,
  settings.CLOUDINARY_API_KEY,
  settings.CLOUDINARY_API_SECRET,
]):
  cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
  )
