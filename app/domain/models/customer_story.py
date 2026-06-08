from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class CustomerStory(Base):
    __tablename__ = "customer_stories"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(140), nullable=False)
    pet_name = Column(String(140), nullable=True)
    customer_title = Column(String(180), nullable=True)
    quote = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False, default=5)
    image_url = Column(String(1200), nullable=True)
    is_featured = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
