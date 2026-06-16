from __future__ import annotations

import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.dto.public_order import (
    PublicOrderCreateBody,
    PublicOrderCreateResponse,
    PublicOrderItemResponse,
    PublicOrderLookupResponse,
    PublicOrderResponseData,
)
from app.core.deps import get_db
from app.core.rate_limit import rate_limit
from app.domain.models.order import Order, OrderStatus
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductVariant, VariantAttributeValue
from app.domain.models.user import User
from app.presentation.api.public_api.deps import get_optional_account_user
from app.application.services.admin_push_notification_service import create_new_order_admin_notification
from app.services.email_service import send_order_email_flow


router = APIRouter(prefix="/orders", tags=["Public Orders"])


def _build_tracking_code() -> str:
    stamp = datetime.utcnow().strftime("%y%m%d")
    random_part = f"{random.randint(0, 999999):06d}"
    return f"LS{stamp}{random_part}"


def _normalize_phone(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+")


def _order_status_text(value: object) -> str:
    raw = getattr(value, "value", value)
    normalized = str(raw or "pending").strip().lower()
    if normalized in {"processed", "processing", "shipped", "delivered"}:
        return "processed"
    if normalized == "cancelled":
        return "cancelled"
    return "pending"


def _variant_label(variant: Optional[ProductVariant]) -> str:
    if variant is None:
        return ""
    values: list[str] = []
    for item in getattr(variant, "attribute_values", None) or []:
        attribute_value = getattr(item, "attribute_value", None)
        value = str(getattr(attribute_value, "value", "") or "").strip()
        if value:
            values.append(value)
    if values:
        return " / ".join(values)
    return str(getattr(variant, "sku", "") or "").strip()


def _order_load_options() -> list[object]:
    return [
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.items)
        .selectinload(OrderItem.variant)
        .selectinload(ProductVariant.attribute_values)
        .selectinload(VariantAttributeValue.attribute_value),
    ]


def _to_order_response(order: Order) -> PublicOrderResponseData:
    items: list[PublicOrderItemResponse] = []
    for item in order.items or []:
        product = getattr(item, "product", None)
        variant = getattr(item, "variant", None)
        product_name = str(getattr(product, "name", "") or f"Sản phẩm #{item.product_id}")
        label = _variant_label(variant)
        if label:
            product_name = f"{product_name} ({label})"

        items.append(
            PublicOrderItemResponse(
                productId=int(item.product_id),
                productVariantId=int(item.product_variant_id) if item.product_variant_id is not None else None,
                name=product_name,
                sku=getattr(variant, "sku", None) or getattr(product, "sku", None),
                quantity=int(item.quantity),
                unitPrice=float(item.price or 0),
                subtotal=float(item.total or 0),
            )
        )

    return PublicOrderResponseData(
        id=int(order.id),
        trackingCode=order.tracking_code,
        status=_order_status_text(order.status),
        paymentStatus=str(order.payment_status or "pending"),
        paymentMethod=str(order.payment_method or "cod"),
        receiverName=order.receiver_name,
        receiverPhone=order.receiver_phone,
        receiverAddress=order.receiver_address,
        totalAmount=float(order.total_amount or 0),
        createdAt=order.created_at,
        items=items,
    )


@router.post("", response_model=PublicOrderCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_public_order(
    body: PublicOrderCreateBody,
    background_tasks: BackgroundTasks,
    _limited: None = Depends(rate_limit("public-checkout", limit=20, window_seconds=300)),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_account_user),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="Order must have at least one item")

    requested_receiver_email = str(body.receiver_email or "").strip().lower()
    account_email = str(getattr(current_user, "email", "") or "").strip().lower() if current_user is not None else ""
    receiver_email = requested_receiver_email or account_email or None

    try:
        product_ids = sorted({int(item.product_id) for item in body.items})
        products_rows = await db.execute(
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.id.in_(product_ids))
        )
        products = {int(p.id): p for p in products_rows.scalars().all()}

        variant_ids = sorted({int(item.product_variant_id) for item in body.items if item.product_variant_id is not None})
        variants: dict[int, ProductVariant] = {}
        if variant_ids:
            variants_rows = await db.execute(select(ProductVariant).where(ProductVariant.id.in_(variant_ids)))
            variants = {int(v.id): v for v in variants_rows.scalars().all()}

        order_items: list[OrderItem] = []
        email_items: list[dict[str, object]] = []
        total_amount = 0.0

        for item in body.items:
            product = products.get(int(item.product_id))
            if product is None:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
            if getattr(product, "deleted_at", None) is not None or str(getattr(product, "status", "active")) != "active" or not bool(getattr(product, "is_active", True)):
                raise HTTPException(status_code=400, detail=f"Product {item.product_id} is not available")

            quantity = int(item.quantity)
            selected_variant: Optional[ProductVariant] = None
            unit_price = float(getattr(product, "sale_price", None) or getattr(product, "price", 0) or 0)

            if item.product_variant_id is not None:
                selected_variant = variants.get(int(item.product_variant_id))
                if selected_variant is None or int(selected_variant.product_id) != int(product.id):
                    raise HTTPException(status_code=400, detail=f"Variant {item.product_variant_id} does not belong to product {product.id}")
                if not bool(getattr(selected_variant, "is_active", True)) or str(getattr(selected_variant, "status", "active")) != "active":
                    raise HTTPException(status_code=400, detail=f"Variant {item.product_variant_id} is not available")

                unit_price = float(getattr(selected_variant, "sale_price", None) or getattr(selected_variant, "price", None) or unit_price)
                manage_stock = bool(getattr(selected_variant, "manage_stock", True))
                allow_backorder = bool(getattr(selected_variant, "allow_backorder", False))
                available_stock = int(getattr(selected_variant, "stock", 0) or 0)
                if manage_stock and not allow_backorder and quantity > available_stock:
                    raise HTTPException(status_code=400, detail=f"Not enough stock for product {product.id}")
                if manage_stock:
                    selected_variant.stock = available_stock - quantity
            else:
                all_variants = list(product.variants or [])
                active_variants = [
                    variant
                    for variant in all_variants
                    if bool(getattr(variant, "is_active", True))
                    and str(getattr(variant, "status", "active") or "active") == "active"
                ]
                if len(active_variants) == 1:
                    selected_variant = active_variants[0]
                    unit_price = float(getattr(selected_variant, "sale_price", None) or getattr(selected_variant, "price", None) or unit_price)
                    manage_stock = bool(getattr(selected_variant, "manage_stock", True))
                    allow_backorder = bool(getattr(selected_variant, "allow_backorder", False))
                    available_stock = int(getattr(selected_variant, "stock", 0) or 0)
                    if manage_stock and not allow_backorder and quantity > available_stock:
                        raise HTTPException(status_code=400, detail=f"Not enough stock for product {product.id}")
                    if manage_stock:
                        selected_variant.stock = available_stock - quantity
                elif len(active_variants) > 1:
                    raise HTTPException(status_code=400, detail=f"Please choose a variant for product {product.id}")
                elif all_variants:
                    raise HTTPException(status_code=400, detail=f"Product {product.id} is not available")
                else:
                    available_stock = int(getattr(product, "stock", 0) or 0)
                    if quantity > available_stock:
                        raise HTTPException(status_code=400, detail=f"Not enough stock for product {product.id}")
                    product.stock = available_stock - quantity

            subtotal = round(unit_price * quantity, 2)
            total_amount += subtotal
            order_items.append(
                OrderItem(
                    product_id=int(product.id),
                    product_variant_id=int(selected_variant.id) if selected_variant is not None else None,
                    quantity=quantity,
                    price=unit_price,
                    total=subtotal,
                )
            )

            display_name = str(getattr(product, "name", "") or f"Sản phẩm #{product.id}").strip()
            email_items.append({"name": display_name, "quantity": quantity, "unit_price": unit_price, "subtotal": subtotal})

        order = Order(
            user_id=int(current_user.id) if current_user is not None else 0,
            status=OrderStatus.PENDING.value,
            total_amount=round(total_amount, 2),
            payment_method=body.payment_method,
            payment_status="pending",
            note=body.note,
            tracking_code=_build_tracking_code(),
            receiver_name=body.receiver_name,
            receiver_phone=body.receiver_phone,
            receiver_address=body.receiver_address,
        )
        db.add(order)
        await db.flush()

        for order_item in order_items:
            order_item.order_id = int(order.id)
            db.add(order_item)

        await db.commit()

        stmt = (
            select(Order)
            .options(*_order_load_options())
            .where(Order.id == order.id)
            .limit(1)
        )
        created_order = (await db.execute(stmt)).scalar_one()

        background_tasks.add_task(
            send_order_email_flow,
            order_id=int(created_order.id),
            tracking_code=str(created_order.tracking_code),
            receiver_name=str(body.receiver_name),
            receiver_phone=str(body.receiver_phone),
            receiver_address=str(body.receiver_address),
            payment_method=str(body.payment_method),
            total_amount=round(total_amount, 2),
            items=email_items,
            receiver_email=receiver_email,
        )
        background_tasks.add_task(
            create_new_order_admin_notification,
            order_id=int(created_order.id),
            tracking_code=str(created_order.tracking_code or ""),
            receiver_name=str(body.receiver_name or ""),
            total_amount=round(total_amount, 2),
            product_names=[str(item.get("name") or "") for item in email_items],
        )

        return {"success": True, "data": _to_order_response(created_order).model_dump(by_alias=True)}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create order: {exc}")


@router.get("/lookup", response_model=PublicOrderLookupResponse)
async def lookup_public_order(
    tracking_code: str = Query(..., alias="trackingCode", min_length=4),
    phone: str = Query(..., min_length=4),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Order)
        .options(*_order_load_options())
        .where(Order.tracking_code == tracking_code, Order.deleted_at.is_(None))
        .limit(1)
    )
    order = (await db.execute(query)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if _normalize_phone(order.receiver_phone) != _normalize_phone(phone):
        raise HTTPException(status_code=403, detail="Phone number does not match order")

    return {"success": True, "data": _to_order_response(order).model_dump(by_alias=True)}
