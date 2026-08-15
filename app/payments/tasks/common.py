"""Payments Celery tasks."""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from core.tasks import BaseTask
from services.telegram import send_telegram_message

from ..models import (
    DoctorTariffPurchase,
    Payment,
    PayoutRequest,
    ProSubscription,
    SystemSetting,
)

logger = logging.getLogger(__name__)

PAYOUT_IN_REVIEW_AFTER_KEY = "payout_in_review_after_minutes"
PAYOUT_IN_REVIEW_AFTER_DEFAULT = 30


# paytechuz PaymentTransaction.state choices (paytechuz/integrations/django/models.py):
# 0 = Created, 1 = Initiating, 2 = Successfully (paid),
# -1 = Cancelled during initiation, -2 = Cancelled after successful performed
_PAYTECHUZ_STATE_PAID = 2
_PAYTECHUZ_STATES_CANCELLED = (-1, -2)


