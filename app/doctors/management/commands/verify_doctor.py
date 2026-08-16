"""Shifokorni tasdiqlash (admin panelsiz, demo/dev uchun).

    python manage.py verify_doctor --list                 # barcha shifokorlar holati
    python manage.py verify_doctor 998901234501           # bittasini tasdiqlash
    python manage.py verify_doctor --all                  # hammasini tasdiqlash

Tasdiqlangan shifokor marketplace'da ko'rinadi va bemor bilan ishlay oladi
(is_verified=True + marketplace_visible=True + specialty majburiy).
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Shifokorni tasdiqlaydi (is_verified=True, marketplace'da ko'rinadi)"

    def add_arguments(self, parser):
        parser.add_argument("phone", nargs="?", help="Shifokor telefon raqami")
        parser.add_argument("--all", action="store_true", help="Barcha shifokorlarni tasdiqlash")
        parser.add_argument("--list", action="store_true", help="Faqat ro'yxatni ko'rsatish")

    def handle(self, *args, **options):
        from app.doctors.models import DoctorProfile, Specialty

        if options["list"]:
            self._list(DoctorProfile)
            return

        if options["all"]:
            profiles = list(DoctorProfile.objects.select_related("user"))
        elif options["phone"]:
            phone = options["phone"].strip().lstrip("+").replace(" ", "")
            user = User.objects.filter(phone=phone).first()
            if not user:
                raise CommandError(f"{phone} raqamli foydalanuvchi topilmadi.")
            profile = DoctorProfile.objects.filter(user=user).first()
            if not profile:
                # Doctor sifatida ro'yxatdan o'tgan, lekin profil yaratilmagan holat
                profile = DoctorProfile.objects.create(user=user)
                self.stdout.write("  DoctorProfile yo'q edi — yaratildi")
            profiles = [profile]
        else:
            raise CommandError("Telefon raqami yoki --all / --list bering.")

        if not profiles:
            self.stdout.write(self.style.WARNING("Shifokor topilmadi."))
            return

        default_specialty = Specialty.objects.first()
        for p in profiles:
            changed = []
            if not p.is_verified:
                p.is_verified = True
                changed.append("verified")
            if not p.marketplace_visible:
                p.marketplace_visible = True
                changed.append("marketplace")
            if not p.specialty_id and default_specialty:
                p.specialty = default_specialty
                changed.append(f"specialty={default_specialty}")
            if getattr(p, "is_deleted", False):
                p.is_deleted = False
                changed.append("restored")
            # Doctor roli JWT scope uchun kerak
            if p.user.role != "doctor" and p.user.role != "admin":
                p.user.role = "doctor"
                p.user.save(update_fields=["role"])
                changed.append("role=doctor")
            p.save()
            status = ", ".join(changed) if changed else "avvaldan tasdiqlangan"
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ {p.user.phone}  {p.user.full_name or '—'}  [{status}]")
            )

        self.stdout.write("")
        self._list(DoctorProfile)

    def _list(self, DoctorProfile):
        rows = DoctorProfile.objects.select_related("user", "specialty").order_by("id")
        if not rows:
            self.stdout.write(self.style.WARNING("Hech qanday shifokor profili yo'q."))
            return
        self.stdout.write("  Shifokorlar:")
        for p in rows:
            mark = "✓" if (p.is_verified and p.marketplace_visible) else "✗"
            spec = getattr(p.specialty, "name_uz", None) or p.specialty_id or "—"
            self.stdout.write(
                f"    {mark} {p.user.phone:<14} {(p.user.full_name or '—'):<22} "
                f"{spec}  verified={p.is_verified} marketplace={p.marketplace_visible}"
            )
