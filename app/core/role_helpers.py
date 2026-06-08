from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


ADMIN_ROLE_NAMES = {"admin", "administrator", "staff", "manager", "superadmin", "super_admin"}
CUSTOMER_ROLE_NAMES = {"customer", "client", "user", "member", "buyer", "shopper"}
ROLE_TABLE_CANDIDATES = ("roles", "role")


def normalize_role_name(value: object) -> str:
    return str(value or "").strip().lower()


async def _fetch_role_name_from_table(db: AsyncSession, table_name: str, role_id: int) -> Optional[str]:
    if table_name not in ROLE_TABLE_CANDIDATES:
        return None

    # Quote table name explicitly to support legacy table name `role` and avoid keyword ambiguity.
    query = text(f'SELECT name FROM "{table_name}" WHERE id = :id LIMIT 1')
    result = await db.execute(query, {"id": int(role_id)})
    raw = result.scalar_one_or_none()
    if raw is None:
        return None
    return normalize_role_name(raw)


async def get_role_name_by_id(db: AsyncSession, role_id: object) -> str:
    try:
        role_id_int = int(role_id)
    except (TypeError, ValueError):
        return ""

    for table_name in ROLE_TABLE_CANDIDATES:
        try:
            name = await _fetch_role_name_from_table(db, table_name, role_id_int)
            if name:
                return name
        except Exception:
            continue

    return ""


async def is_admin_role(db: AsyncSession, role_id: object) -> bool:
    role_name = await get_role_name_by_id(db, role_id)
    return role_name in ADMIN_ROLE_NAMES


async def is_customer_role(db: AsyncSession, role_id: object) -> bool:
    role_name = await get_role_name_by_id(db, role_id)
    return role_name in CUSTOMER_ROLE_NAMES


async def get_or_create_customer_role_id(db: AsyncSession) -> int:
    expected_names = tuple(sorted(CUSTOMER_ROLE_NAMES))
    in_clause = ", ".join(f"'{name}'" for name in expected_names)

    for table_name in ROLE_TABLE_CANDIDATES:
        try:
            # Prefer exact customer-like role lookup first.
            select_existing = text(
                f'SELECT id, name FROM "{table_name}" '
                f'WHERE lower(name) IN ({in_clause}) '
                'ORDER BY id ASC LIMIT 1'
            )
            existing = await db.execute(select_existing)
            row = existing.first()
            if row is not None:
                return int(row[0])

            created = await db.execute(
                text(f'INSERT INTO "{table_name}" (name) VALUES (:name) RETURNING id'),
                {"name": "customer"},
            )
            created_id = created.scalar_one_or_none()
            if created_id is not None:
                return int(created_id)
        except Exception:
            # Handle race: another request may have inserted customer role right before this one.
            try:
                retry_existing = await db.execute(
                    text(
                        f'SELECT id, name FROM "{table_name}" '
                        f'WHERE lower(name) IN ({in_clause}) '
                        'ORDER BY id ASC LIMIT 1'
                    ),
                )
                retry_row = retry_existing.first()
                if retry_row is not None:
                    return int(retry_row[0])
            except Exception:
                continue

    raise RuntimeError("Cannot resolve customer role from either roles or role table")
