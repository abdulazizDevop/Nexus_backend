"""Diet AI yordamchi xizmatlar.

- User context builder (bemor profilini prompt uchun tayyorlash)
- Daily limit checker (bepul 10/kun, Pro cheksiz)
- Conversation message limit (yangi chat boshlash tavsiyasi)
"""

import json
import re
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from app.health_packages.models import HealthIndicator, HealthIndicatorType
from app.medical.models import MedicalCard, MedicalCondition
from app.payments.utils import has_pro_feature
from app.treatment.models import DailyCalorieLimit, Treatment
from core.i18n import pick_translation

from ..models import (
    DietConversation,
    DietDailyUsage,
    DietEntry,
    DietProfile,
    DietRestriction,
)


User = get_user_model()
