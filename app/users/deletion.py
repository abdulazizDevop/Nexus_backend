"""Profilma-profil akkaunt o'chirish (Yandex-Taxi identity).

Uch rejim (`me/delete-account` scope param bilan):
  - scope="doctor"  → FAQAT doctor profili o'chadi (User bemor sifatida qoladi).
  - scope="patient" → FAQAT bemor datasi o'chadi (doctor bo'lsa User doctor
                      sifatida qoladi; bo'lmasa butun akkaunt soft-delete).
  - scope="all"     → butun akkaunt (hozirgi _soft_delete_user — legacy default).

Printsip (locked): OPERATSION data + PII TO'LIQ o'chadi; MOLIYAVIY/AUDIT
yozuvlar (to'lovlar, DoctorBalance, sotuvlar, payout, review, yakunlangan
uchrashuvlar) ANONIM SAQLANADI — admin statistikasi tushmasin. Buning uchun
DoctorProfile qatori o'chirilmaydi, balki anonimlashtirilib "retire" qilinadi
(financial FK'lar unga CASCADE bog'langan); bemor tomonda esa faqat operatsion
jadvallar tozalanadi, moliyaviy yozuvlar (User orqali) qoladi.
"""

import logging
import uuid

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("mediik.users.deletion")


def _purge_doctor_operational_data(doctor_profile) -> None:
    """Doctor-tomon OPERATSION datasi (moliyaviy EMAS) — to'liq o'chadi."""
    from app.chat.models import ChatAIDailyUsage, ChatRoom
    from app.diet_ai.models import DietRestriction
    from app.doctors.models import DoctorCertificate, DoctorPatient, Slot
    from app.health_ai.models import AiConversation, AIHealthReport
    from app.medical.models import Analysis, MedicalCard, MedicalCondition, MedicalNote
    from app.payments.models import DoctorPayoutCard, DoctorTariff
    from app.treatment.models import DailyCalorieLimit, Treatment

    dp = doctor_profile

    # 1. Sof doctor yozuvlari — jismonan o'chadi (moliyaviy emas).
    Slot.objects.filter(doctor=dp).delete()
    DoctorCertificate.objects.filter(doctor=dp).delete()
    DoctorPatient.objects.filter(doctor=dp).delete()
    DoctorPayoutCard.objects.filter(doctor=dp).delete()  # karta PII
    DoctorTariff.objects.filter(doctor=dp).delete()  # purchase.tariff SET_NULL
    AIHealthReport.objects.filter(doctor=dp).delete()
    AiConversation.objects.filter(doctor_profile=dp).delete()
    ChatAIDailyUsage.objects.filter(doctor=dp).delete()
    dp.specialties.clear()

    # 2. Bemor-ownerли data ustidagi doctor MUALLIF-referensini uzish
    #    (data bemorda qoladi, doctor bog'lanishi yo'qoladi).
    Treatment.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    DailyCalorieLimit.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    MedicalCard.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    MedicalCondition.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    MedicalNote.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    Analysis.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    DietRestriction.objects.filter(doctor_profile=dp).update(doctor_profile=None)
    ChatRoom.objects.filter(doctor=dp).update(doctor=None)


def _retire_doctor_profile(doctor_profile) -> None:
    """DoctorProfile'ni anonimlashtirib "retire" qiladi (qator SAQLANADI).

    Moliyaviy/audit (DoctorBalance, DoctorTariffPurchase, OfflinePayment,
    PayoutRequest, BalanceTopup, Review, Appointment) shu qatorga CASCADE
    bog'langan — qator o'chsa ular ham o'chardi. Shuning uchun saqlaymiz,
    faqat PII/mazmun tozalanadi va katalogdan yashiriladi.
    """
    dp = doctor_profile
    dp.bio = ""
    dp.workplace = ""
    dp.license_number = ""
    dp.specialty = None
    dp.is_verified = False
    dp.is_deleted = True
    dp.deleted_at = timezone.now()
    dp.save(
        update_fields=[
            "bio", "workplace", "license_number", "specialty",
            "is_verified", "is_deleted", "deleted_at", "updated_at",
        ]
    )


def delete_doctor_profile(user) -> bool:
    """FAQAT doctor profilini o'chiradi. User bemor sifatida tirik qoladi.

    Returns True — o'chirildi; False — doctor profili yo'q edi.
    """
    doctor_profile = getattr(user, "doctor_profile", None)
    if not doctor_profile or doctor_profile.is_deleted:
        return False

    with transaction.atomic():
        _purge_doctor_operational_data(doctor_profile)
        _retire_doctor_profile(doctor_profile)

    logger.info("Doctor profil o'chirildi (retire): user_id=%s", user.id)
    return True


def _purge_patient_operational_data(user) -> None:
    """Bemor-tomon OPERATSION datasi (moliyaviy EMAS) — to'liq o'chadi.

    Moliyaviy yozuvlar (Payment, ProSubscription, DoctorTariffPurchase,
    OfflinePayment) User orqali qoladi — bu funksiya ularga tegmaydi.
    """
    from app.chat.models import ChatAIDailyUsage
    from app.diet_ai.models import (
        DietConversation,
        DietDailyUsage,
        DietEntry,
        DietRestriction,
    )
    from app.doctors.models import DoctorPatient
    from app.health_packages.models import DailySituationCheckup, HealthIndicator
    from app.medical.models import Analysis, MedicalCard, MedicalCondition, MedicalNote
    from app.payments.models import AtmosSavedCard
    from app.treatment.models import DailyCalorieLimit, Treatment, TreatmentLog

    # Muolaja — bemor o'chirsa TO'LIQ ketadi (arxiv tarixi ham; bu bemor
    # o'zining datasini o'chirishi, admin statistikasi muolajaga bog'liq emas).
    TreatmentLog.objects.filter(user=user).delete()
    Treatment.objects.filter(user=user).delete()
    DailyCalorieLimit.objects.filter(patient=user).delete()

    # Salomatlik / tibbiy karta / diet
    HealthIndicator.objects.filter(user=user).delete()
    DailySituationCheckup.objects.filter(user=user).delete()
    MedicalNote.objects.filter(user=user).delete()
    MedicalCondition.objects.filter(user=user).delete()
    Analysis.objects.filter(patient=user).delete()
    MedicalCard.objects.filter(user=user).delete()
    DietRestriction.objects.filter(patient=user).delete()
    DietEntry.objects.filter(user=user).delete()
    DietConversation.objects.filter(user=user).delete()
    DietDailyUsage.objects.filter(user=user).delete()
    ChatAIDailyUsage.objects.filter(patient=user).delete()

    # Bemor↔doctor bog'lanishlari + saqlangan karta (PII)
    DoctorPatient.objects.filter(patient=user).delete()
    AtmosSavedCard.objects.filter(user=user).delete()


def delete_patient_data(user, reason="", refresh_token="") -> str:
    """Bemor datasini o'chiradi.

    - Doctor profili YO'Q → butun akkaunt soft-delete (legacy _soft_delete_user).
    - Doctor profili BOR → faqat bemor operatsion datasi tozalanadi, User +
      doctor identity + PII (ism/telefon — doctor uchun kerak) qoladi.

    Returns: "account" (butun akkaunt o'chdi) yoki "patient_only" (faqat data).
    """
    has_live_doctor = user.has_doctor_profile  # is_deleted=False ni ham tekshiradi

    if not has_live_doctor:
        from app.users.views import _soft_delete_user

        _soft_delete_user(user, reason=reason, refresh_token=refresh_token)
        return "account"

    with transaction.atomic():
        _purge_patient_operational_data(user)
    logger.info("Bemor datasi o'chirildi (doctor qoldi): user_id=%s", user.id)
    return "patient_only"
