"""Async push notification yuborish tasklari."""

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction

from core.tasks import BaseTask
from services.apns_voip import send_voip_to_user

from ..models import Notification
from ..utils import notify, notify_by_key, send_to_user, send_to_users


User = get_user_model()


logger = logging.getLogger(__name__)


def _get_user_or_none(user_id: int):
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
