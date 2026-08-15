"""notifications views — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.notifications.views import X` ishlaydi — urls.py buzilmaydi.
"""

from .notification import (
    NotificationViewSet,
)
from .device import (
    AdminDeviceTokenSerializer,
    AdminDeviceTokenViewSet,
    DeviceTokenViewSet,
)
from .broadcast import (
    AdminBroadcastViewSet,
    BroadcastSerializer,
)

__all__ = [
    "NotificationViewSet",
    "AdminDeviceTokenSerializer",
    "AdminDeviceTokenViewSet",
    "DeviceTokenViewSet",
    "AdminBroadcastViewSet",
    "BroadcastSerializer",
]
