import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from paytechuz.integrations.django.views import (
    BaseClickWebhookView,
    BasePaymeWebhookView,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.doctors.models import DoctorPatient, DoctorProfile
from app.notifications.catalog import render as render_notif
from app.notifications.models import Notification
from app.notifications.tasks import notify_by_key_user, notify_user
from app.notifications.utils import notify
from core.i18n import pick_translation
from core.permissions import (
    IsDoctor,
    IsPatient,
    IsSuperOrSimpleAdmin,
    IsVerifiedDoctor,
    get_request_role,
)
from services.payments import get_provider

from ..utils import (
    build_pro_payment,
    build_tariff_payment,
    build_topup_payment,
    get_active_pro_subscription,
    has_active_doctor_tariff,
    is_bank_business_day,
    resolve_commission,
)

User = get_user_model()

from ..models import (
    BalanceTopup,
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
from ..serializers import (
    DoctorBalanceSerializer,
    DoctorPayoutCardSerializer,
    DoctorSalesStatsSerializer,
    DoctorTariffAdminSerializer,
    DoctorTariffPublicSerializer,
    DoctorTariffPurchaseSerializer,
    DoctorTariffSerializer,
    GrantProSerializer,
    InvoiceResponseSerializer,
    MyProStatusSerializer,
    OfflinePaymentCreateSerializer,
    OfflinePaymentSerializer,
    OfflineRejectSerializer,
    PayoutListResponseSerializer,
    PaymentAdminSerializer,
    PayoutRequestAdminSerializer,
    PayoutRequestCreateSerializer,
    PayoutRequestSerializer,
    ProFeatureFlagSerializer,
    ProPlanPublicSerializer,
    ProPlanSerializer,
    ProSubscriptionSerializer,
    PurchaseRequestSerializer,
    RejectTariffSerializer,
    RevokeProResponseSerializer,
    SubscribeRequestSerializer,
    SystemSettingSerializer,
    TopupRequestSerializer,
    WalletOperationSerializer,
    WalletSummarySerializer,
)

logger = logging.getLogger("mediik.payments")

PAYOUT_MIN_AMOUNT_KEY = "min_payout_amount"
PAYOUT_MIN_AMOUNT_DEFAULT = 50000  # so'm

PAYOUT_MAX_PENDING_KEY = "max_pending_payouts_per_doctor"
PAYOUT_MAX_PENDING_DEFAULT = 3

PAYOUT_HOLD_DAYS_KEY = "payout_hold_days"
PAYOUT_HOLD_DAYS_DEFAULT = 2  # kalendar kun — har tarif xaridi shu muddatdan keyin payoutga ochiladi

PAYOUT_BUSINESS_DAYS_ONLY_KEY = "payout_business_days_only"
PAYOUT_BUSINESS_DAYS_ONLY_DEFAULT = False  # ATMOS ASL 24/7 ishlaydi — odatda gate kerak emas. Admin yoqsa Du-Ju gate ishlaydi.

TOPUP_MIN_AMOUNT_KEY = "balance_topup_min_amount"
TOPUP_MIN_AMOUNT_DEFAULT = 10000  # so'm — doctor balansini to'ldirish minimal summasi


# --- Umumiy helperlar (bir necha submodul ishlatadi) ---


def _get_doctor_profile(request):
    """Doctor profile'ni topib qaytaradi (yo'q bo'lsa yaratadi)."""

    profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
    return profile


def _not_found():
    """Standart 'Topilmadi.' 404 javobi (profil yoki obyekt topilmaganda)."""
    return Response({"detail": "Topilmadi."}, status=404)


def _require_asl_configured():
    """ATMOS ASL sozlanmagan bo'lsa 503 Response qaytaradi, aks holda None."""
    from services.payments.atmos_asl import atmos_asl_client

    if not atmos_asl_client.is_configured():
        return Response({"detail": "ATMOS ASL sozlanmagan."}, status=503)
    return None


def _parse_date_range(request, default_days=30):
    """?from / ?to query'larini oqiydi; bo'sh bo'lsa oxirgi `default_days` kun."""
    date_to = request.query_params.get("to") or timezone.localdate().isoformat()
    date_from = request.query_params.get("from") or (
        timezone.localdate() - timezone.timedelta(days=default_days)
    ).isoformat()
    return date_from, date_to


def _parse_page(request):
    """?page query'sini 1'dan kichik bo'lmagan int sifatida oqiydi (default 1)."""
    try:
        return max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        return 1


def _tiyin_to_sum(value):
    """ATMOS tiyin (int) → so'm. None'ni 0 deb qabul qiladi."""
    return (value or 0) / 100


def _annotate_sum_fields(obj: dict, field_map) -> None:
    """obj['<src>'] mavjud bo'lsa obj['<dst>'] = tiyin→so'm qiymatini qo'shadi.

    field_map: [("amount", "amount_sum"), ...]. ATMOS javoblarida tiyin'dagi
    summalarni so'mga aylantirib qo'shimcha maydon sifatida joylaydi.
    """
    for src, dst in field_map:
        if src in obj:
            obj[dst] = _tiyin_to_sum(obj[src])
