from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float, Enum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base
from app.domain.models.order_item import OrderItem

# class Order(Base):
#     id = Column(Integer, primary_key=True, index=True)
#     customer_id = Column(Integer, ForeignKey("customer.id"))
#     total_price = Column(Numeric(10, 2))
#     status = Column(String, default="pending")
#     created_at = Column(DateTime(timezone=True), server_default=func.now())

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    CANCELLED = "cancelled"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    status = Column(
        Enum(
            OrderStatus,
            name="orderstatus",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=OrderStatus.PENDING.value,
    )
    total_amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=False)
    payment_status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    tracking_code = Column(String(100), nullable=True)
    receiver_name = Column(String, nullable=True)
    receiver_phone = Column(String)
    receiver_address = Column(Text, nullable=True)
