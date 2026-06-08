from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, func
from datetime import datetime
from app.core.database import Base

class ShippingConfig(Base):
    __tablename__ = "shipping_config"

    id = Column(Integer, primary_key=True)
    api_token = Column(String(255))
    sender_name = Column(String(100))
    sender_phone = Column(String(15))
    sender_address = Column(String(255))
    province = Column(String(100))
    district = Column(String(100))
    ward = Column(String(100))
    sender_province_id = Column(Integer)
    sender_district_id = Column(Integer)
    sender_ward_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
