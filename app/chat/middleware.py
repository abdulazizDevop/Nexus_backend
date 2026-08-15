from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()


class JWTAuthMiddleware(BaseMiddleware):
    """WebSocket uchun JWT auth — ?token=xxx query param dan oladi.

    Phase 3: scope claim ham extract qilinadi va `scope["jwt_scope"]` ga
    yoziladi (consumer Message.objects.create da sender_scope sifatida ishlatadi).
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = dict(
            param.split("=", 1) for param in query_string.split("&") if "=" in param
        )
        token = params.get("token")

        if token:
            user, jwt_scope = await self._get_user_and_scope(token)
            scope["user"] = user
            scope["jwt_scope"] = jwt_scope
        else:
            scope["user"] = AnonymousUser()
            scope["jwt_scope"] = None

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _get_user_and_scope(self, token_str):
        try:
            access_token = AccessToken(token_str)
            # is_active=True — deaktiv qilingan user eski (muddati o'tmagan) token
            # bilan WS'ga ulana olmasin (REST SIMPLE_JWT CHECK_USER_IS_ACTIVE bilan
            # tekshiradi, WS middleware shu paritetni ta'minlaydi). DoesNotExist →
            # AnonymousUser → ulanish rad etiladi (consumer connect'da 4001).
            user = User.objects.get(id=access_token["user_id"], is_active=True)
            # scope (yangi) yoki active_role (legacy fallback)
            jwt_scope = access_token.payload.get("scope") or access_token.payload.get(
                "active_role"
            )
            return user, jwt_scope
        except Exception:
            return AnonymousUser(), None
