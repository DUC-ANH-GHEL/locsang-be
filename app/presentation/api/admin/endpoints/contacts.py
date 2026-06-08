from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.domain.models.contact import Contact
from app.domain.models.user import User


router = APIRouter()


class ContactReadBody(BaseModel):
    is_read: bool = True


def _to_contact_summary(contact: Contact) -> dict:
    return {
        "id": int(contact.id),
        "name": str(contact.name or ""),
        "email": str(contact.email or ""),
        "phone": str(contact.phone or ""),
        "subject": contact.subject,
        "is_read": bool(contact.is_read),
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def _to_contact_detail(contact: Contact) -> dict:
    data = _to_contact_summary(contact)
    data["message"] = str(contact.message or "")
    data["customer_id"] = int(contact.customer_id) if contact.customer_id is not None else None
    return data


@router.get("")
async def admin_list_contacts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = []

    if search and search.strip():
        q = f"%{search.strip()}%"
        filters.append(
            or_(
                Contact.name.ilike(q),
                Contact.email.ilike(q),
                Contact.phone.ilike(q),
                Contact.subject.ilike(q),
                Contact.message.ilike(q),
            )
        )

    if is_read is not None:
        filters.append(Contact.is_read.is_(is_read))

    count_stmt = select(func.count(Contact.id))
    if filters:
        count_stmt = count_stmt.where(and_(*filters))
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = (
        select(Contact)
        .order_by(Contact.created_at.desc(), Contact.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    if filters:
        stmt = stmt.where(and_(*filters))

    rows = (await db.execute(stmt)).scalars().all()
    data = [_to_contact_summary(row) for row in rows]

    return {
        "data": data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    }


@router.get("/{contact_id}")
async def admin_get_contact_detail(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Contact).where(Contact.id == contact_id).limit(1)
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    return {"data": _to_contact_detail(contact)}


@router.patch("/{contact_id}/read")
async def admin_update_contact_read_status(
    contact_id: int,
    body: ContactReadBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Contact).where(Contact.id == contact_id).limit(1)
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.is_read = bool(body.is_read)
    contact.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(contact)

    return {"data": _to_contact_detail(contact)}


@router.delete("/{contact_id}")
async def admin_delete_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Contact).where(Contact.id == contact_id).limit(1)
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    await db.delete(contact)
    await db.commit()

    return {"success": True}
