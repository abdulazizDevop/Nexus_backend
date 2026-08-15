"""auth view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.auth.views import X` ishlashda davom etadi — urls.py va bot.py
(`_is_valid_doctor_referral`) importlari buzilmaydi.
"""

from .auth import AuthViewSet
from .common import _is_valid_doctor_referral
from .token import TokenRefreshView

__all__ = ["AuthViewSet", "TokenRefreshView", "_is_valid_doctor_referral"]
