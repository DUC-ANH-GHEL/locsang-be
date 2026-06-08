from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class TipPost(Base):
    __tablename__ = "tip_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(220), nullable=False)
    slug = Column(String(260), nullable=False, unique=True, index=True)
    excerpt = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    template_key = Column(String(80), nullable=True)
    content_blocks = Column(JSONB, nullable=False, default=list)
    featured_image = Column(String(1200), nullable=True)
    category = Column(String(120), nullable=True)
    tags = Column(JSONB, nullable=False, default=list)
    status = Column(String(40), nullable=False, default="draft")
    featured = Column(Boolean, nullable=False, default=False)
    seo_title = Column(String(320), nullable=True)
    seo_description = Column(String(500), nullable=True)
    published_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
