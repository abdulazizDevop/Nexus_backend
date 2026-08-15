from .common import *  # noqa: F401,F403
from .common import _BaseTokenRefreshView  # underscore alias (star import bermaydi)


class _SafeTokenRefreshSerializer(TokenRefreshSerializer):
    """SimpleJWT refresh paytida user mavjudligini tekshiradi (is_active uchun).
    User O'CHIRILGAN (akkaunt o'chirilgan) bo'lsa-yu client'da refresh token qolsa,
    `User.DoesNotExist` ushlanmay 500 berardi. Endi 401 (token_not_valid) — client
    logout qiladi. (is_active=False holati SimpleJWT'da allaqachon 401.)"""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except User.DoesNotExist as exc:
            raise InvalidToken("Foydalanuvchi topilmadi yoki o'chirilgan.") from exc


@extend_schema(tags=["Auth"])
class TokenRefreshView(_BaseTokenRefreshView):
    """Custom — o'chirilgan user uchun 500 emas, 401 qaytaradi."""

    serializer_class = _SafeTokenRefreshSerializer


