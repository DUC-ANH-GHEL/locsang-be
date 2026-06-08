from sqlalchemy import Column, Integer, ForeignKey, Numeric, String, DateTime, func
from datetime import datetime
from app.core.database import Base

class ShippingInfo(Base):
    __tablename__ = "shipping_info"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    recipient_name = Column(String(100))
    recipient_phone = Column(String(15))
    address = Column(String(255))
    province = Column(String(100))
    district = Column(String(100))
    ward = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
