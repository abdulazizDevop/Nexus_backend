"""Default test foydalanuvchilarni yaratish (faqat dev uchun).

Foydalanish:
    python manage.py create_test_users

DESTRUCTIVE — agar shu telefon raqamlari bilan user mavjud bo'lsa, u
(va unga bog'liq barcha data: DoctorProfile, appointments, treatments,
chat xabarlari va h.k.) CASCADE o'chiriladi va yangidan yaratiladi.

Yaratiladigan userlar:
    Doctor:  998000000001  (Test Doctor)   — DoctorProfile bilan (is_verified=True)
    Patient: 998000000002  (Test Patient)

998000... prefiksi — Uzbekistan dial code (998) + 00 (bo'sh operator kodi) —
hech qachon real raqam bo'lmaydi.

OTP kodi: settings.DEFAULT_OTP_CODE (default: 7777)
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()


TEST_USERS = [
    {
        "phone": "998000000001",
        "full_name": "Test Doctor",
        "role": "doctor",
    },
    {
        "phone": "998000000002",
        "full_name": "Test Patient",
        "role": "patient",
    },
]


class Command(BaseCommand):
    help = "Default test foydalanuvchilarni yaratadi (eski bo'lsa o'chirib qayta yaratadi)"

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        otp_code = getattr(settings, "DEFAULT_OTP_CODE", "0000")

        self.stdout.write(
            self.style.MIGRATE_HEADING("Test foydalanuvchilar yangilanmoqda...")
        )
        self.stdout.write("")

        for data in TEST_USERS:
            # 1-qadam: eski userni o'chirish (CASCADE orqali bog'liq data ham)
            existing = User.objects.filter(phone=data["phone"]).first()
            if existing:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [O'CHIRILDI]  {data['role']:8s}  {data['phone']}  "
                        f"→  id={existing.id} {existing.full_name}"
                    )
                )
                existing.delete()

            # 2-qadam: yangi user yaratish
            user = User.objects.create(
                phone=data["phone"],
                full_name=data["full_name"],
                role=data["role"],
                active_role=data["role"],
                is_active=True,
            )

            # 3-qadam: DoctorProfile (agar doctor bo'lsa)
            if user.role == "doctor":
                from app.doctors.models import DoctorProfile

                DoctorProfile.objects.create(
                    user=user,
                    is_verified=True,
                    bio="Test doctor profile",
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"  [YARATILDI]  {data['role']:8s}  {data['phone']}  "
                    f"→  id={user.id} {user.full_name}"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Tayyor!"))
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Login uchun:"))
        self.stdout.write(f"  Doctor:  phone=998000000001, otp={otp_code}")
        self.stdout.write(f"  Patient: phone=998000000002, otp={otp_code}")
        self.stdout.write("")
