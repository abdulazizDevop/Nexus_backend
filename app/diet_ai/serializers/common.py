from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from services.storage import generate_download_url

from ..models import (
    DietConversation,
    DietEntry,
    DietMessage,
    DietProfile,
    DietRestriction,
)


def _image_url(key):
    return generate_download_url(key) if key else None


def _has_image(msg):
    return bool(msg.image_key and msg.image_key.strip())
