"""chat view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.chat.views import X` ishlashda davom etadi — urls.py buzilmaydi.
"""

from .admin import AdminChatRoomViewSet
from .online import OnlineStatusView
from .rooms import ChatRoomViewSet
from .support import SupportChatViewSet

__all__ = [
    "ChatRoomViewSet",
    "SupportChatViewSet",
    "OnlineStatusView",
    "AdminChatRoomViewSet",
]
