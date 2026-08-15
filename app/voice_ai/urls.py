from django.urls import path

from .views import VoiceLiveTokenView, VoicePersonasView

urlpatterns = [
    path("personas/", VoicePersonasView.as_view(), name="voice-personas"),
    path("live-token/", VoiceLiveTokenView.as_view(), name="voice-live-token"),
]
