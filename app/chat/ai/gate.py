"""AI gatekeeper gate + kunlik limit hisoblagich.

`should_ai_handle` ham consumer (database_sync_to_async ichida), ham Celery
task'da (sync) chaqiriladi — toza sinxron funksiya.
"""

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from app.chat.models import ChatAIDailyUsage, ChatRoom
from app.payments.models import DoctorTariff, SystemSetting
from app.payments.utils import has_active_doctor_tariff

from .constants import CHAT_AI_DAILY_CAP_DEFAULT, CHAT_AI_DAILY_CAP_KEY


def get_sellable_tariffs(doctor_profile):
    """AI sotadigan takliflar (approved + active), ustuvorlik bo'yicha."""
    return DoctorTariff.objects.filter(
        doctor=doctor_profile,
        status=DoctorTariff.Status.APPROVED,
        is_active=True,
    ).order_by("-is_popular", "price")


def _has_live_access(user, doctor) -> bool:
    """Bemorda jonli (AI'siz) kirish bormi? — aktiv DoctorTariffPurchase."""
    return has_active_doctor_tariff(user, doctor)


def should_ai_handle(room, sender_user, jwt_scope):
    """AI tarifsiz bemorga javob berishi kerakmi?

    Returns: (bool, doctor_profile | None)
    Shartlar: consultation room · sender = bemor · room.doctor bor · bemorda
    aktiv tarif YO'Q · doctor'da sotiladigan tarif BOR.
    """
    if room.room_type != ChatRoom.RoomType.CONSULTATION:
        return False, None
    if jwt_scope != "patient":
        return False, None
    if not (room.patient_id and room.patient and room.patient.user_id == sender_user.id):
        return False, None
    doctor = room.doctor
    if not doctor:
        return False, None
    # Bemorda jonli kirish (tarif yoki klinika paketi) → AI yo'q.
    if _has_live_access(sender_user, doctor):
        return False, None
    # Doctor'da sotiladigan tarif yo'q → sotadigan narsa yo'q → normal chat.
    if not get_sellable_tariffs(doctor).exists():
        return False, None
    return True, doctor


def daily_cap() -> int:
    return SystemSetting.get_int(CHAT_AI_DAILY_CAP_KEY, CHAT_AI_DAILY_CAP_DEFAULT)


def ai_usage_state(room, user):
    """Bemor AI-rejimда kunlik limit holati (dict) yoki None (AI-rejim emas).

    AI-rejim = consultation room · user = room bemori · aktiv tarif YO'Q ·
    doctor'da sotiladigan tarif BOR. Mobil chat ochilganda limit banner uchun.
    """
    if room.room_type != ChatRoom.RoomType.CONSULTATION:
        return None
    if not (room.patient_id and room.patient and room.patient.user_id == user.id):
        return None
    doctor = room.doctor
    if not doctor:
        return None
    if _has_live_access(user, doctor):
        return None
    if not get_sellable_tariffs(doctor).exists():
        return None
    cap = daily_cap()
    count = usage_count(user, doctor)
    remaining = max(0, cap - count)
    return {
        "count": count,
        "cap": cap,
        "remaining": remaining,
        "limit_reached": remaining <= 0,
    }


def usage_count(patient_user, doctor_profile) -> int:
    today = timezone.localdate()
    u = ChatAIDailyUsage.objects.filter(
        patient=patient_user, doctor=doctor_profile, date=today
    ).first()
    return u.replies_count if u else 0


def under_cap(patient_user, doctor_profile) -> bool:
    return usage_count(patient_user, doctor_profile) < daily_cap()


def increment_chat_ai_usage(
    patient_user, doctor_profile, tokens_input: int = 0, tokens_output: int = 0
) -> None:
    """Kunlik hisoblagichni +1 (atomic upsert — diet_ai.increment_usage namunasi)."""
    today = timezone.localdate()
    updated = ChatAIDailyUsage.objects.filter(
        patient=patient_user, doctor=doctor_profile, date=today
    ).update(
        replies_count=F("replies_count") + 1,
        tokens_input=F("tokens_input") + tokens_input,
        tokens_output=F("tokens_output") + tokens_output,
    )
    if updated:
        return
    try:
        ChatAIDailyUsage.objects.create(
            patient=patient_user,
            doctor=doctor_profile,
            date=today,
            replies_count=1,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
        )
    except IntegrityError:
        ChatAIDailyUsage.objects.filter(
            patient=patient_user, doctor=doctor_profile, date=today
        ).update(
            replies_count=F("replies_count") + 1,
            tokens_input=F("tokens_input") + tokens_input,
            tokens_output=F("tokens_output") + tokens_output,
        )
