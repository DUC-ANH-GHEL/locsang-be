from typing import Optional, List
from app.domain.models.order import Order, OrderStatus, PaymentStatus
from app.domain.models.order_item import OrderItem
from app.infrastructure.repositories.order_repository import OrderRepository
from app.application.services.base import BaseServiceImpl
from app.application.dto.order import OrderCreate, OrderUpdate, OrderResponse
from app.core.exceptions import ValidationException
from sqlalchemy.ext.asyncio import AsyncSession

class OrderService(BaseServiceImpl[Order, OrderCreate, OrderUpdate]):
    """Order service implementation"""

    def __init__(self, repository: OrderRepository):
        super().__init__(repository)
        self.repository = repository

    async def create(self, dto: OrderCreate, user_id: int) -> Order:
        """Create a new order"""
        receiver_phone = getattr(dto, "receiver_phone", None) or getattr(dto, "shipping_phone", None)
        # Create order
        order = Order(
            user_id=user_id,
            payment_method=dto.payment_method,
            receiver_phone=receiver_phone,
            note=dto.note,
            status=OrderStatus.PENDING.value,
            payment_status=PaymentStatus.PENDING.value,
            total_amount=0  # Will be calculated after adding items
        )

        # Add order items
        total_amount = 0
        for item_dto in dto.items:
            # Get product price and check stock
            product = await self._get_product(item_dto.product_id)
            if product.stock < item_dto.quantity:
                raise ValidationException(f"Insufficient stock for product {product.name}")

            # Create order item
            item = OrderItem(
                product_id=item_dto.product_id,
                quantity=item_dto.quantity,
                price=product.price,
                total=product.price * item_dto.quantity
            )
            order.items.append(item)
            total_amount += item.total

            # Update product stock
            product.stock -= item_dto.quantity

        # Set order total amount
        order.total_amount = total_amount

        return await self.repository.create(order)

    async def update(self, id: int, dto: OrderUpdate) -> Optional[Order]:
        """Update an order"""
        order = await self.repository.get_by_id(id)
        if not order:
            return None

        # Update order fields
        update_data = dto.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(order, field, value)

        return await self.repository.update(id, order)

    async def get_by_user_id(self, user_id: int) -> List[Order]:
        """Get orders by user ID"""
        return await self.repository.get_by_user_id(user_id)

    async def get_by_status(self, status: OrderStatus) -> List[Order]:
        """Get orders by status"""
        return await self.repository.get_by_status(status)

    async def get_by_payment_status(self, payment_status: PaymentStatus) -> List[Order]:
        """Get orders by payment status"""
        return await self.repository.get_by_payment_status(payment_status)

    async def get_user_orders_by_status(self, user_id: int, status: OrderStatus) -> List[Order]:
        """Get user orders by status"""
        return await self.repository.get_user_orders_by_status(user_id, status)

    async def get_user_orders_by_payment_status(self, user_id: int, payment_status: PaymentStatus) -> List[Order]:
        """Get user orders by payment status"""
        return await self.repository.get_user_orders_by_payment_status(user_id, payment_status)

    async def _get_product(self, product_id: int):
        """Get product by ID"""
        # This should be implemented using a product repository
        # For now, we'll raise an error
        raise NotImplementedError("Product repository not implemented")

    def _map_dto_to_entity(self, dto: OrderCreate | OrderUpdate) -> Order:
        """Map DTO to Order entity"""
        if isinstance(dto, OrderCreate):
            receiver_phone = getattr(dto, "receiver_phone", None) or getattr(dto, "shipping_phone", None)
            return Order(
                payment_method=dto.payment_method,
                receiver_phone=receiver_phone,
                note=dto.note
            )
        else:
            return Order(**dto.dict(exclude_unset=True))
