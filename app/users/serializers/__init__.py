"""users serializerlari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.users.serializers import X` ishlashda davom etadi — users/views.py buzilmaydi.
"""

from .actions import ChangeRoleSerializer, DeleteMyAccountSerializer
from .admin import UserAdminDetailSerializer, UserAdminSerializer
from .full_info import UserFullInfoSerializer
from .user import UserSerializer, UserSettingsSerializer, UserUpdateSerializer

__all__ = [
    "UserSettingsSerializer",
    "UserSerializer",
    "UserUpdateSerializer",
    "UserAdminSerializer",
    "UserAdminDetailSerializer",
    "UserFullInfoSerializer",
    "DeleteMyAccountSerializer",
    "ChangeRoleSerializer",
]
