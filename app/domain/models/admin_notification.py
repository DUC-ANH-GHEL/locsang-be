from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class AdminNotification(Base):
    __tablename__ = "admin_notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), nullable=False, default="order")
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    url = Column(String(500), nullable=True)
    order_id = Column(Integer, nullable=True, index=True)
    tracking_code = Column(String(100), nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
