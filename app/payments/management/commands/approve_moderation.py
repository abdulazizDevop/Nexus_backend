"""Moderatsiya kutayotgan tarif va konsultatsiyalarni tasdiqlash (demo/dev).

    python manage.py approve_moderation --list        # kutayotganlar ro'yxati
    python manage.py approve_moderation --all         # hammasini tasdiqlash
    python manage.py approve_moderation --tariffs     # faqat tariflar
    python manage.py approve_moderation --consultations
    python manage.py approve_moderation --phone 998901234501   # bitta shifokorniki

Prod'da bu ish admin panel orqali qilinadi — bu komanda demo uchun.
"""

from django.core.management.base import BaseCommand, CommandError

OK = "✓"
WAIT = "…"


class Command(BaseCommand):
    help = "Kutayotgan doctor tariflari va konsultatsiyalarni tasdiqlaydi"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="Faqat ro'yxat")
        parser.add_argument("--all", action="store_true", help="Tarif + konsultatsiya")
        parser.add_argument("--tariffs", action="store_true", help="Faqat tariflar")
        parser.add_argument("--consultations", action="store_true", help="Faqat konsultatsiyalar")
        parser.add_argument("--phone", help="Faqat shu shifokorniki")

    def handle(self, *args, **o):
        from app.doctors.models import DoctorProfile
        from app.payments.models import DoctorTariff

        phone = (o.get("phone") or "").strip().lstrip("+").replace(" ", "") or None

        if o["list"] or not (o["all"] or o["tariffs"] or o["consultations"]):
            self._list(DoctorTariff, DoctorProfile, phone)
            if o["list"]:
                return
            raise CommandError(
                "Nima qilishni tanlang: --all | --tariffs | --consultations"
            )

        if o["all"] or o["tariffs"]:
            self._approve_tariffs(DoctorTariff, phone)
        if o["all"] or o["consultations"]:
            self._approve_consultations(DoctorProfile, phone)

        self.stdout.write("")
        self._list(DoctorTariff, DoctorProfile, phone)

    # --- ro'yxat ---

    def _list(self, DoctorTariff, DoctorProfile, phone):
        tq = DoctorTariff.objects.select_related("doctor__user")
        cq = DoctorProfile.objects.select_related("user").filter(consultation_enabled=True)
        if phone:
            tq = tq.filter(doctor__user__phone=phone)
            cq = cq.filter(user__phone=phone)

        self.stdout.write(self.style.MIGRATE_HEADING("\n  Doctor tariflari"))
        if not tq:
            self.stdout.write("    (yo'q)")
        for t in tq:
            mark = OK if t.status == DoctorTariff.Status.APPROVED else WAIT
            self.stdout.write(
                f"    {mark} #{t.id} {t.doctor.user.phone:<14} {str(t.name)[:28]:<30} "
                f"{t.price} so'm / {t.duration_days} kun  [{t.status}] active={t.is_active}"
            )

        self.stdout.write(self.style.MIGRATE_HEADING("\n  Konsultatsiyalar (doctor profili)"))
        if not cq:
            self.stdout.write("    (konsultatsiya yoqilgan shifokor yo'q)")
        for p in cq:
            mark = OK if p.consultation_status == "approved" else WAIT
            self.stdout.write(
                f"    {mark} {p.user.phone:<14} {(p.user.full_name or '—'):<22} "
                f"{p.consultation_price or 0} so'm / {p.consultation_duration_min or 0} daq  "
                f"[{p.consultation_status}]"
            )
        self.stdout.write("")

    # --- tasdiqlash ---

    def _approve_tariffs(self, DoctorTariff, phone):
        qs = DoctorTariff.objects.exclude(status=DoctorTariff.Status.APPROVED)
        if phone:
            qs = qs.filter(doctor__user__phone=phone)
        n = 0
        for t in qs.select_related("doctor__user"):
            t.status = DoctorTariff.Status.APPROVED
            t.is_active = True
            t.save()
            self.stdout.write(
                self.style.SUCCESS(f"  {OK} Tarif #{t.id} tasdiqlandi — {t.doctor.user.phone}")
            )
            n += 1
        if not n:
            self.stdout.write("  (tasdiqlanmagan tarif yo'q)")

    def _approve_consultations(self, DoctorProfile, phone):
        qs = DoctorProfile.objects.filter(consultation_enabled=True).exclude(
            consultation_status="approved"
        )
        if phone:
            qs = qs.filter(user__phone=phone)
        n = 0
        for p in qs.select_related("user"):
            if not p.consultation_price:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! {p.user.phone} — narx qo'yilmagan, o'tkazib yuborildi"
                    )
                )
                continue
            p.consultation_status = "approved"
            p.consultation_rejection_reason = ""
            p.save(update_fields=["consultation_status", "consultation_rejection_reason"])
            self.stdout.write(
                self.style.SUCCESS(f"  {OK} Konsultatsiya tasdiqlandi — {p.user.phone}")
            )
            n += 1
        if not n:
            self.stdout.write("  (tasdiqlanmagan konsultatsiya yo'q)")
