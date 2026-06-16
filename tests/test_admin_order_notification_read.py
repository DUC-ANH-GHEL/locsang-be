from datetime import datetime

import pytest

from app.domain.models.admin_notification import AdminNotification
from app.presentation.api.admin.endpoints.orders import _mark_order_notifications_read


class _FakeScalarResult:
    def __init__(self, notifications):
        self._notifications = notifications

    def all(self):
        return self._notifications


class _FakeExecuteResult:
    def __init__(self, notifications):
        self._notifications = notifications

    def scalars(self):
        return _FakeScalarResult(self._notifications)


class _FakeSession:
    def __init__(self, notifications):
        self.notifications = notifications
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _FakeExecuteResult(self.notifications)


@pytest.mark.anyio
async def test_mark_order_notifications_read_marks_only_unread_order_notifications():
    unread = AdminNotification(
        id=1,
        type="order",
        title="Có đơn hàng mới",
        body="Đơn mới",
        order_id=42,
    )
    read_at = datetime.utcnow()
    already_read = AdminNotification(
        id=2,
        type="order",
        title="Có đơn hàng mới",
        body="Đơn đã đọc",
        order_id=42,
        read_at=read_at,
    )
    session = _FakeSession([unread])

    updated = await _mark_order_notifications_read(session, 42)

    assert updated == 1
    assert unread.read_at is not None
    assert unread.updated_at == unread.read_at
    assert already_read.read_at == read_at
    assert "admin_notifications.order_id IN (42)" in str(
        session.statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "admin_notifications.read_at IS NULL" in str(
        session.statement.compile(compile_kwargs={"literal_binds": True})
    )
