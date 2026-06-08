from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.domain.models.order import Order
from app.domain.models.order_item import OrderItem
from app.application.dto.order import OrderCreate, OrderUpdate

class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, order: Order) -> Order:
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def get_by_id(self, order_id: int) -> Optional[Order]:
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Order]:
        return self.db.query(Order).offset(skip).limit(limit).all()

    def get_by_customer_id(self, customer_id: int, skip: int = 0, limit: int = 100) -> List[Order]:
        return self.db.query(Order).filter(Order.customer_id == customer_id).offset(skip).limit(limit).all()

    def update(self, order_id: int, order_data: dict) -> Optional[Order]:
        order = self.get_by_id(order_id)
        if not order:
            return None

        for field, value in order_data.items():
            setattr(order, field, value)

        self.db.commit()
        self.db.refresh(order)
        return order

    def delete(self, order_id: int) -> bool:
        order = self.get_by_id(order_id)
        if not order:
            return False

        self.db.delete(order)
        self.db.commit()
        return True

    def create_order_item(self, order_item: OrderItem) -> OrderItem:
        self.db.add(order_item)
        self.db.commit()
        self.db.refresh(order_item)
        return order_item

    def get_order_items(self, order_id: int) -> List[OrderItem]:
        return self.db.query(OrderItem).filter(OrderItem.order_id == order_id).all()

    def update_order_item(self, order_item_id: int, order_item_data: dict) -> Optional[OrderItem]:
        order_item = self.db.query(OrderItem).filter(OrderItem.id == order_item_id).first()
        if not order_item:
            return None

        for field, value in order_item_data.items():
            setattr(order_item, field, value)

        self.db.commit()
        self.db.refresh(order_item)
        return order_item

    def delete_order_item(self, order_item_id: int) -> bool:
        order_item = self.db.query(OrderItem).filter(OrderItem.id == order_item_id).first()
        if not order_item:
            return False

        self.db.delete(order_item)
        self.db.commit()
        return True
