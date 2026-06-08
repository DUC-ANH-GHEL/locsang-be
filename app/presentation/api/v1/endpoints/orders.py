from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.domain.models.user import User
from app.domain.models.order import OrderStatus, PaymentStatus
from app.application.dto.order import OrderCreate, OrderUpdate, OrderResponse
from app.application.services.order_service import OrderService
from app.infrastructure.repositories.order_repository import OrderRepository
from app.core.exceptions import NotFoundException, ValidationException

router = APIRouter()

def get_order_service(db: AsyncSession = Depends(get_db)) -> OrderService:
    """Get order service instance"""
    repository = OrderRepository(db)
    return OrderService(repository)

@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_in: OrderCreate,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user)
):
    """Create new order"""
    try:
        order = await order_service.create(order_in, current_user.id)
        return order
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/", response_model=List[OrderResponse])
async def get_orders(
    skip: int = 0,
    limit: int = 100,
    status: OrderStatus = None,
    payment_status: PaymentStatus = None,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user)
):
    """Get all orders with optional filters"""
    if status and payment_status:
        orders = await order_service.get_user_orders_by_status(current_user.id, status)
        orders = [o for o in orders if o.payment_status == payment_status]
    elif status:
        orders = await order_service.get_user_orders_by_status(current_user.id, status)
    elif payment_status:
        orders = await order_service.get_user_orders_by_payment_status(current_user.id, payment_status)
    else:
        orders = await order_service.get_by_user_id(current_user.id)

    return orders[skip : skip + limit]

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user)
):
    """Get order by ID"""
    try:
        order = await order_service.get_by_id(order_id)
        if order.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this order"
            )
        return order
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.put("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: int,
    order_in: OrderUpdate,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user)
):
    """Update order"""
    try:
        order = await order_service.get_by_id(order_id)
        if order.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this order"
            )

        updated_order = await order_service.update(order_id, order_in)
        if not updated_order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        return updated_order
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: int,
    order_service: OrderService = Depends(get_order_service),
    current_user: User = Depends(get_current_user)
):
    """Delete order"""
    try:
        order = await order_service.get_by_id(order_id)
        if order.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this order"
            )

        success = await order_service.delete(order_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
