from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.i18n import pick_for
from core.serializers import TranslatableFieldsMixin

from ..models import (
    DoctorBalance,
    DoctorPayoutCard,
    DoctorTariff,
    DoctorTariffPurchase,
    OfflinePayment,
    Payment,
    PayoutRequest,
    ProFeatureFlag,
    ProPlan,
    ProSubscription,
    SystemSetting,
)


# --- SystemSetting ---
