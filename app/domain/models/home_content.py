from datetime import datetime

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class HomeContent(Base):
    __tablename__ = "home_contents"

    id = Column(Integer, primary_key=True, index=True)
    draft_content = Column(JSONB, nullable=False, default=dict)
    published_content = Column(JSONB, nullable=False, default=dict)
    updated_by = Column(Integer, nullable=True)
    published_by = Column(Integer, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
