from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class AccountCartItem(Base):
    __tablename__ = "account_cart_items"
    __table_args__ = (UniqueConstraint("user_id", "item_key", name="uq_account_cart_user_item_key"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    item_key = Column(String(120), nullable=False)
    product_id = Column(Integer, nullable=True)
    product_variant_id = Column(Integer, nullable=True)
    sku = Column(String(120), nullable=True)
    variant_label = Column(String(255), nullable=True)
    title = Column(String(255), nullable=False)
    image = Column(String(1000), nullable=False, default="")
    price = Column(Float, nullable=False, default=0)
    quantity = Column(Integer, nullable=False, default=1)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User")
