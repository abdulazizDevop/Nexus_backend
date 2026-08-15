from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import re_path

from . import consumers


class NotFoundConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.close(code=4404)


websocket_urlpatterns = [
    re_path(r"ws/chat/(?P<room_id>\d+)/$", consumers.ChatConsumer.as_asgi()),
    re_path(r"ws/presence/$", consumers.PresenceConsumer.as_asgi()),  # app-level presence
    re_path(r".*", NotFoundConsumer.as_asgi()),
]
