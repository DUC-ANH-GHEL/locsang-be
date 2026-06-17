from app.domain.models.admin_notification import AdminNotification
from app.presentation.api.admin.endpoints.notifications import _notification_ordering


def test_notification_list_orders_unread_before_read():
    stmt = str(
        AdminNotification.__table__
        .select()
        .order_by(*_notification_ordering())
        .compile(compile_kwargs={"literal_binds": True})
    )

    assert "admin_notifications.read_at IS NULL" in stmt
    assert "THEN 0 ELSE 1" in stmt
    assert "admin_notifications.created_at DESC" in stmt
