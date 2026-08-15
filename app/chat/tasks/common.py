import logging
import os
import subprocess
import tempfile
import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.utils import timezone

from app.chat.models import CallSession, ChatRoom, Message
from app.chat.utils import chat_peer_ids, get_last_seen, is_online
from app.notifications.models import Notification
from app.notifications.tasks import notify_by_key_user, send_push_to_user
from app.notifications.utils import notify
from core.tasks import BaseTask
from services.storage import (
    delete_file,
    download_file_bytes,
    generate_download_url,
    upload_file_bytes,
)

# --- Voice transcode (web webm/opus → m4a) ---
# Untrusted webm fayl (medical app) — DoS himoyasi uchun qattiq limitlar.
TRANSCODE_MAX_INPUT_BYTES = 20 * 1024 * 1024   # >20MB → skip + failed (buzuq/abuse)
TRANSCODE_MAX_DURATION_SEC = 300               # ffmpeg -t 300 — max 5 daqiqa cap
TRANSCODE_FFMPEG_TIMEOUT_SEC = 30              # subprocess timeout — osilib qolmasin
TRANSCODE_TARGET_MIME = "audio/mp4"            # m4a
TRANSCODE_OLD_DELETE_COUNTDOWN = 86400         # eski webm 24h'dan keyin o'chiriladi

User = get_user_model()
logger = logging.getLogger(__name__)

