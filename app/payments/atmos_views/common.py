"""Atmos endpointlari — karta qo'shish, to'lov, webhook.

Acquiring only — payout flow keyin qo'shiladi (Atmos shartnoma docs kelgach).
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from core.permissions import IsPatient
from services.payments.atmos import AtmosError, atmos_client

from ..utils import (
    build_pro_payment,
    build_tariff_payment,
    decimal_to_tiyin as _decimal_to_tiyin,
    get_active_pro_subscription,
)

from ..atmos_serializers import (
    AtmosCardBindResponseSerializer,
    AtmosCardBindSerializer,
    AtmosCardConfirmSerializer,
    AtmosConfirmResponseSerializer,
    AtmosConfirmSerializer,
    AtmosPayResponseSerializer,
    AtmosPaySerializer,
    AtmosSavedCardSerializer,
)
from ..models import (
    AtmosSavedCard,
    DoctorTariff,
    Payment,
    ProPlan,
)

logger = logging.getLogger("mediik.payments")


class OtpConfirmThrottle(UserRateThrottle):
    """OTP tasdiqlash endpointlari uchun per-user throttle.

    Karta bind / to'lov OTP'sini brute-force qilishni cheklaydi (ATMOS
    tomonidagi cheklovga qo'shimcha defense-in-depth). Rate kodda qattiq
    belgilangan — settings scope'ga bog'liq emas.
    """

    scope = "atmos_otp_confirm"

    def get_rate(self):
        return "10/minute"


# ---------- Helpers ----------


def _atmos_error_response(exc: AtmosError):
    return Response(
        {"detail": exc.description, "code": exc.code},
        status=status.HTTP_400_BAD_REQUEST,
    )


# ---------- Karta boshqaruvi ----------
