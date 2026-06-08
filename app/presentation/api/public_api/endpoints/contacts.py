from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto.contact import ContactCreate, ContactCreateResponse, ContactOut
from app.core.database import get_db
from app.domain.models.contact import Contact
from app.services.email_service import send_contact_email_flow


router = APIRouter(prefix='/contacts', tags=['Public Contacts'])


def _is_missing_contacts_table_error(exc: Exception) -> bool:
    message = str(exc or '').lower()
    return 'relation "contacts" does not exist' in message


async def _ensure_contacts_table_exists(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                phone VARCHAR(20),
                subject VARCHAR(200),
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                customer_id INTEGER,
                created_at TIMESTAMP WITHOUT TIME ZONE,
                updated_at TIMESTAMP WITHOUT TIME ZONE,
                deleted_at TIMESTAMP WITHOUT TIME ZONE
            )
            """
        )
    )
    await db.execute(text("CREATE INDEX IF NOT EXISTS ix_contacts_id ON contacts (id)"))
    await db.commit()


async def _persist_contact_with_repair(db: AsyncSession, contact: Contact) -> Contact:
    db.add(contact)
    try:
        await db.flush()
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        if not _is_missing_contacts_table_error(exc):
            raise

        await _ensure_contacts_table_exists(db)
        repaired = Contact(
            name=contact.name,
            phone=contact.phone,
            message=contact.message,
            email=contact.email,
            subject=contact.subject,
        )
        db.add(repaired)
        await db.flush()
        await db.commit()
        await db.refresh(repaired)
        return repaired

    await db.refresh(contact)
    return contact


@router.post('', response_model=ContactCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    name = str(body.name or '').strip()
    phone = str(body.phone or '').strip()
    message = str(body.message or '').strip()
    email = str(body.email or '').strip().lower()
    subject = str(body.subject or '').strip() or None

    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Name is required')
    if not phone:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Phone is required')
    if not message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Message is required')

    contact = Contact(
        name=name,
        phone=phone,
        message=message,
        email=email,
        subject=subject,
    )

    contact = await _persist_contact_with_repair(db, contact)

    background_tasks.add_task(
        send_contact_email_flow,
        contact_id=int(contact.id),
        name=name,
        phone=phone,
        message=message,
        email=email or None,
        subject=subject,
    )

    return ContactCreateResponse(
        message='Lộc Sang da nhan duoc tin nhan cua ban.',
        data=ContactOut.model_validate(contact),
    )
