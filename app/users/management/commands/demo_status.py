"""Demo holatini bir ko'rishda tekshirish.

    python manage.py demo_status

Nima ko'rsatadi: foydalanuvchilar, shifokorlar (tasdiqlangan/yo'q), bemor
ma'lumotlari (tashxis, yo'l xaritasi, muolajalar, ko'rsatkichlar, kayfiyat),
oila bog'lanishlari, AI hisobotlar, retsept skanlar va AI/SMS konfiguratsiyasi.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

OK = "✓"
NO = "✗"


class Command(BaseCommand):
    help = "Demo ma'lumotlari va konfiguratsiya holatini ko'rsatadi"

    def handle(self, *args, **options):
        self._config()
        self._users()
        self._doctors()
        self._patients()
        self._ai()

    def _line(self, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n  {title}"))

    def _config(self):
        self._line("Konfiguratsiya")
        vertex = getattr(settings, "GEMINI_USE_VERTEX", False)
        self.stdout.write(f"    AI rejimi         : {'Vertex AI' if vertex else 'API key'}")
        self.stdout.write(f"    Gemini model      : {getattr(settings, 'GEMINI_MODEL', '—')}")
        self.stdout.write(f"    To'lovlar         : {'YOQILGAN' if getattr(settings, 'PAYMENTS_ENABLED', False) else 'demo rejim (503)'}")
        bypass = getattr(settings, "BYPASS_PHONE_NUMBERS", [])
        self.stdout.write(f"    OTP bypass raqam  : {len(bypass)} ta {bypass if bypass else '(yo`q — SMS kerak)'}")
        self.stdout.write(f"    ALLOWED_HOSTS     : {', '.join(settings.ALLOWED_HOSTS) or '(bo`sh!)'}")
        cors = getattr(settings, "CORS_ALLOWED_ORIGINS", [])
        self.stdout.write(f"    CORS origin       : {len(cors)} ta")

    def _users(self):
        self._line("Foydalanuvchilar")
        total = User.objects.count()
        by_role = {}
        for r in User.objects.values_list("role", flat=True):
            by_role[r] = by_role.get(r, 0) + 1
        self.stdout.write(f"    Jami: {total}  →  " + ", ".join(f"{k}: {v}" for k, v in by_role.items()))

    def _doctors(self):
        from app.doctors.models import DoctorPatient, DoctorProfile

        self._line("Shifokorlar")
        rows = DoctorProfile.objects.select_related("user", "specialty")
        if not rows:
            self.stdout.write("    (yo'q)")
            return
        for p in rows:
            mark = OK if (p.is_verified and p.marketplace_visible) else NO
            spec = getattr(p.specialty, "name_uz", None) or "—"
            n_pat = DoctorPatient.objects.filter(
                doctor=p, status=DoctorPatient.Status.ACCEPTED
            ).count()
            self.stdout.write(
                f"    {mark} {p.user.phone:<14} {(p.user.full_name or '—'):<22} "
                f"{spec:<18} bemorlar: {n_pat}"
            )
        self.stdout.write(f"    Marketplace'da ko'rinadi: "
                          f"{rows.filter(is_verified=True, marketplace_visible=True).count()}")

    def _patients(self):
        from app.health_packages.models import DailySituationCheckup, HealthIndicator
        from app.medical.models import MedicalCard, MedicalCondition, RoadmapStep
        from app.treatment.models import Treatment, TreatmentLog

        self._line("Bemorlar (ma'lumoti bor)")
        ids = set(HealthIndicator.objects.values_list("user_id", flat=True))
        ids |= set(Treatment.objects.values_list("user_id", flat=True))
        ids |= set(MedicalCondition.objects.values_list("user_id", flat=True))
        if not ids:
            self.stdout.write("    (ma'lumotli bemor yo'q — `manage.py seed_demo` ishlating)")
            return

        for u in User.objects.filter(id__in=ids):
            self.stdout.write(f"\n    {u.phone}  {u.full_name or '—'}")
            card = MedicalCard.objects.filter(user=u).first()
            self.stdout.write(
                f"      Tibbiy karta   : {OK + ' ' + (card.primary_disease or 'to`ldirilgan') if card else NO}"
            )
            cond = MedicalCondition.objects.filter(user=u, is_active=True).first()
            if cond:
                n_steps = RoadmapStep.objects.filter(condition=cond).count()
                n_done = RoadmapStep.objects.filter(condition=cond, status="done").count()
                self.stdout.write(
                    f"      Aktiv tashxis  : {OK} {cond.name} ({cond.icd10 or 'ICD yo`q'}), "
                    f"manba: {cond.source}"
                )
                self.stdout.write(
                    f"      Yo'l xaritasi  : {OK if n_steps else NO} {n_done}/{n_steps} qadam bajarilgan"
                )
            else:
                self.stdout.write(f"      Aktiv tashxis  : {NO}")

            n_tr = Treatment.objects.filter(user=u, status="active").count()
            n_log = TreatmentLog.objects.filter(user=u).count()
            self.stdout.write(f"      Muolajalar     : {n_tr} aktiv, {n_log} log")

            n_ind = HealthIndicator.objects.filter(user=u).count()
            last = HealthIndicator.objects.filter(user=u).select_related(
                "indicator_type"
            ).order_by("-recorded_at").first()
            last_txt = (
                f" (oxirgisi: {last.indicator_type.name_uz} {last.display_value})" if last else ""
            )
            self.stdout.write(f"      Ko'rsatkichlar : {n_ind}{last_txt}")
            self.stdout.write(
                f"      Kayfiyat       : {DailySituationCheckup.objects.filter(user=u).count()} kun"
            )
            self._family_of(u)

    def _family_of(self, user):
        try:
            from app.family.models import FamilyLink
        except ImportError:
            return
        links = FamilyLink.objects.filter(patient=user).select_related("member")
        if not links:
            self.stdout.write(f"      Oila a'zolari  : {NO}")
            return
        for l in links:
            self.stdout.write(
                f"      Oila a'zosi    : {OK if l.status == 'accepted' else NO} "
                f"{l.member.full_name} ({l.get_relation_display()}, {l.status})"
            )

    def _ai(self):
        self._line("AI ma'lumotlari")
        try:
            from app.tracking_ai.models import AITrackingReport

            reports = AITrackingReport.objects.select_related("patient").order_by("-period_start")
            self.stdout.write(f"    Tracking hisobotlar: {reports.count()}")
            for r in reports[:3]:
                self.stdout.write(
                    f"      {r.period_start} {r.patient.full_name} [{r.severity}] "
                    f"{(r.summary or '')[:70]}..."
                )
        except ImportError:
            pass

        try:
            from app.treatment.models import PrescriptionScan

            scans = PrescriptionScan.objects.all()
            self.stdout.write(f"    Retsept skanlar    : {scans.count()} "
                              f"(tasdiqlangan: {scans.filter(status='confirmed').count()})")
        except ImportError:
            pass

        try:
            from app.navigator.models import NavConversation, NavMessage

            self.stdout.write(
                f"    Navigator suhbat   : {NavConversation.objects.count()} "
                f"({NavMessage.objects.count()} xabar)"
            )
        except ImportError:
            pass

        self.stdout.write("")
