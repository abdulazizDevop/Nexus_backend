from .common import *  # noqa: F401,F403
from .common import _get_user_or_none  # underscore (star bermaydi)


@shared_task(base=BaseTask, bind=True, name="notifications.send_push_to_user")
def send_push_to_user(
    self,
    user_id: int,
    title: str,
    body: str,
    data: dict | None = None,
    data_only: bool = False,
    app_scope: str | None = None,
):
    """Faqat push (DB yozuvsiz). Ephemeral signallar uchun — incoming_call kabi."""
    user = _get_user_or_none(user_id)
    if user is None:
        return {"error": "user_not_found"}

    return send_to_user(
        user, title, body, data or {}, data_only=data_only, app_scope=app_scope
    )


@shared_task(base=BaseTask, bind=True, name="notifications.send_push_to_users")
def send_push_to_users(
    self,
    user_ids: list[int],
    title: str,
    body: str,
    data: dict | None = None,
    data_only: bool = False,
    app_scope: str | None = None,
):
    """Faqat push broadcast (DB yozuvsiz). Yangi kod uchun `notify_users` ishlatilsin."""
    users = User.objects.filter(pk__in=user_ids)
    return send_to_users(
        users, title, body, data or {}, data_only=data_only, app_scope=app_scope
    )


@shared_task(base=BaseTask, bind=True, name="notifications.send_voip_call_push")
def send_voip_call_push(self, user_id: int, payload: dict, app_scope: str | None = None):
    """iOS VoIP PushKit push — incoming call uchun (CallKit ringtone).

    Android va Web platforma uchun FCM push alohida yuboriladi (send_push_to_user).
    """
    user = _get_user_or_none(user_id)
    if user is None:
        return {"error": "user_not_found"}

    return send_voip_to_user(user, payload, app_scope=app_scope)
