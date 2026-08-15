"""Pro subscription va feature entitlement helpers.

User modeliga property qo'shish o'rniga bu yerda funksiya sifatida yoziladi
(circular import oldini olish uchun).
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import (
    DoctorTariff,
    DoctorTariffPurchase,
    Payment,
    ProFeatureFlag,
    ProSubscription,
    SystemSetting,
)

DEFAULT_COMMISSION_KEY = "doctor_commission_percent"
DEFAULT_COMMISSION_VALUE = 15  # foiz


def resolve_commission(doctor) -> Decimal:
    """Doctor komissiya foizi (%): individual (DoctorProfile.commission_percent)
    berilgan bo'lsa o'sha, aks holda global SystemSetting[doctor_commission_percent]
    (default 15).

    getattr duck-typing — DoctorProfile importsiz (circular import oldini olish);
    doctor None bo'lsa ham global qiymatga tushadi.
    """
    own = getattr(doctor, "commission_percent", None)
    if own is not None:
        return Decimal(str(own))
    return SystemSetting.get_decimal(DEFAULT_COMMISSION_KEY, DEFAULT_COMMISSION_VALUE)


def build_pro_payment(user, plan, provider_name):
    """Pro obuna uchun Payment yaratadi (plan_snapshot bilan).

    Snapshot shaklini bir joyda saqlaydi — REST (ProSubscribeView) va ATMOS
    (AtmosPayView) ikkalasi ham shu factory'ni ishlatishi shart, aks holda
    snapshot drift webhook-completed flow'da yashirin xato keltiradi.
    """
    return Payment.objects.create(
        user=user,
        amount=plan.price,
        provider=provider_name,
        purpose=Payment.Purpose.PRO_SUBSCRIPTION,
        metadata={
            "plan_id": plan.id,
            "plan_snapshot": {
                "name": plan.name,
                "duration_days": plan.duration_days,
                "price": str(plan.price),
            },
        },
    )


def build_tariff_payment(user, tariff, provider_name):
    """Doctor tarif xaridi uchun Payment yaratadi (tariff_snapshot bilan).

    `amount` — tariff.get_price_for(user) (aksiya/chegirma hisobga olingan).
    Snapshot shakli barcha provider'lar uchun yagona manbada.
    """
    amount = tariff.get_price_for(user)
    return Payment.objects.create(
        user=user,
        amount=amount,
        provider=provider_name,
        purpose=Payment.Purpose.DOCTOR_TARIFF,
        metadata={
            "tariff_id": tariff.id,
            "doctor_id": tariff.doctor_id,
            "tariff_snapshot": {
                "name": tariff.name,
                "price": str(tariff.price),
                "final_price": str(amount),
                "duration_days": tariff.duration_days,
                "features": tariff.features,
            },
        },
    )


def build_consultation_payment(user, consultation, provider_name):
    """Konsultatsiya (bir martalik video-qabul) uchun Payment yaratadi.

    `amount` — consultation.amount (booking paytidagi snapshot). Webhook
    yakunlanganda `_confirm_consultation` konsultatsiyani CONFIRMED qiladi,
    doctor balansiga komissiyasiz-qismini qo'shadi va avto-connect qiladi.
    """
    return Payment.objects.create(
        user=user,
        amount=consultation.amount,
        provider=provider_name,
        purpose=Payment.Purpose.CONSULTATION,
        metadata={
            "consultation_id": consultation.id,
            "doctor_id": consultation.doctor_id,
            "consultation_snapshot": {
                "date": str(consultation.date),
                "start_time": str(consultation.start_time),
                "end_time": str(consultation.end_time),
                "amount": str(consultation.amount),
            },
        },
    )


def build_topup_payment(doctor_user, doctor_profile, amount, provider_name):
    """Doctor balansini to'ldirish uchun Payment yaratadi.

    To'lov DOCTOR tomonidan amalga oshiriladi (user=doctor_user). Webhook
    yakunlanganda `_create_balance_topup` to'liq summani balansga qo'shadi
    (komissiyasiz). `doctor_profile_id` metadata — webhook DoctorProfile'ni
    topishi uchun (payment.user fallback ham bor).
    """
    return Payment.objects.create(
        user=doctor_user,
        amount=amount,
        provider=provider_name,
        purpose=Payment.Purpose.BALANCE_TOPUP,
        metadata={"doctor_profile_id": doctor_profile.id},
    )


def has_active_doctor_tariff(patient, doctor) -> bool:
    """Bemorda shu doctor uchun aktiv (muddati o'tmagan) tarif xaridi bormi?

    `doctor` — DoctorProfile instance yoki uning id'si.
    """
    if not patient or not getattr(patient, "is_authenticated", False):
        return False
    doctor_id = getattr(doctor, "id", doctor)
    return DoctorTariffPurchase.objects.filter(
        patient=patient,
        doctor_id=doctor_id,
        expires_at__gt=timezone.now(),
    ).exists()


def doctor_has_sellable_tariff(doctor) -> bool:
    """Doctor'da sotuvga chiqarilgan (approved + active) tarif bormi?"""
    doctor_id = getattr(doctor, "id", doctor)
    return DoctorTariff.objects.filter(
        doctor_id=doctor_id,
        status=DoctorTariff.Status.APPROVED,
        is_active=True,
    ).exists()


def requires_tariff_purchase(patient, doctor) -> bool:
    """Bemor shu doctor bilan JONLI bog'lanish (meeting/booking) uchun tarif olishi shartmi?

    True = doctor sotuvdagi tarifga ega VA bemorда aktiv tarif yo'q.
    Doctor'da sotiladigan tarif yo'q bo'lsa — False (bloklamaymiz, dead-end bo'lmasin —
    chat AI gate mantig'i bilan bir xil).
    """
    if has_active_doctor_tariff(patient, doctor):
        return False

    return doctor_has_sellable_tariff(doctor)


def decimal_to_tiyin(amount: Decimal) -> int:
    """Decimal so'mni ATMOS kutadigan tiyin'ga (int) o'giradi.

    50000.00 so'm → 5000000 tiyin. ROUND_HALF_UP — pul uchun kanonik standart
    (banker's rounding emas). Acquiring (atmos_views) va payout (atmos_asl_service)
    ikkalasi ham shu yagona helper'ni ishlatishi shart — yarim-tiyin holatlarda
    summalar bir xil yaxlitlanishi uchun.
    """
    return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def has_active_pro(user) -> bool:
    """Userda aktiv Pro obuna bormi?"""
    if not user or not user.is_authenticated:
        return False
    return ProSubscription.objects.filter(
        user=user, expires_at__gt=timezone.now()
    ).exists()


def has_pro_feature(user, feature_key: str) -> bool:
    """User Pro obunaga ega VA feature aktiv bo'lsa True."""
    if not has_active_pro(user):
        return False
    return ProFeatureFlag.objects.filter(key=feature_key, is_active=True).exists()


def get_active_pro_subscription(user):
    """Aktiv Pro obunani qaytaradi yoki None."""
    if not user or not user.is_authenticated:
        return None
    return (
        ProSubscription.objects.filter(user=user, expires_at__gt=timezone.now())
        .select_related("plan")
        .order_by("-expires_at")
        .first()
    )


# --- Payout business-day helpers ---

PAYOUT_HOLIDAYS_KEY = "payout_holidays"

# Admin paneldan SystemSetting["payout_holidays"] JSON list orqali o'zgartiriladi.
# Default — O'zbekiston davlat bayramlari (yangi yil oxirida yangilanadi).
PAYOUT_HOLIDAYS_DEFAULT_UZ = [
    "2026-01-01",  # Yangi yil
    "2026-01-14",  # Vatan himoyachilari kuni
    "2026-03-08",  # Xalqaro xotin-qizlar kuni
    "2026-03-21",  # Navro'z
    "2026-05-09",  # Xotira va qadrlash kuni
    "2026-09-01",  # Mustaqillik kuni
    "2026-10-01",  # O'qituvchi va murabbiylar kuni
    "2026-12-08",  # Konstitutsiya kuni
]


def _load_holidays() -> set[date]:
    """SystemSetting'dan bayramlar ro'yxatini o'qiydi. Bo'sh bo'lsa default UZ ro'yxati."""
    raw = SystemSetting.get(PAYOUT_HOLIDAYS_KEY, None)
    if not raw or not isinstance(raw, list):
        raw = PAYOUT_HOLIDAYS_DEFAULT_UZ

    result: set[date] = set()
    for item in raw:
        try:
            result.add(datetime.strptime(str(item), "%Y-%m-%d").date())
        except (ValueError, TypeError):
            continue
    return result


def is_bank_business_day(d: date | None = None) -> bool:
    """Bank ish kunimi: Du-Ju VA bayram emas. Asia/Tashkent timezone'dagi sana."""
    if d is None:
        d = timezone.localdate()
    if d.weekday() >= 5:  # 5=Shanba, 6=Yakshanba
        return False
    return d not in _load_holidays()
