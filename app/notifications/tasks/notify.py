from .common import *  # noqa: F401,F403
from .common import _get_user_or_none  # underscore (star bermaydi)


@shared_task(base=BaseTask, bind=True, name="notifications.notify_user")
def notify_user(
    self,
    user_id: int,
    type: str,
    title: str,
    body: str,
    data: dict | None = None,
    send_push: bool = True,
    app_scope: str | None = None,
):
    """Bitta userga Notification yozuv + push (async)."""
    user = _get_user_or_none(user_id)
    if user is None:
        return {"error": "user_not_found"}

    notification = notify(
        user,
        type=type,
        title=title,
        body=body,
        data=data or {},
        send_push=send_push,
        app_scope=app_scope,
    )
    return {"notification_id": notification.id if notification else None}


@shared_task(base=BaseTask, bind=True, name="notifications.notify_by_key_user")
def notify_by_key_user(
    self,
    user_id: int,
    type: str,
    key: str,
    params: dict | None = None,
    data: dict | None = None,
    send_push: bool = True,
    app_scope: str | None = None,
):
    """Celery async wrapper `notify_by_key` uchun (catalog + user til avtomatik)."""
    user = _get_user_or_none(user_id)
    if user is None:
        return {"error": "user_not_found"}

    notification = notify_by_key(
        user,
        type=type,
        key=key,
        params=params or {},
        data=data or {},
        send_push=send_push,
        app_scope=app_scope,
    )
    return {"notification_id": notification.id if notification else None}
