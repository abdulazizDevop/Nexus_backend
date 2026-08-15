"""Voice AI konteksti — tracking bo'limi testlari."""

from django.utils import timezone

from app.tracking_ai.models import AITrackingReport
from app.voice_ai.context import build_patient_context
from tests.base import BaseAPITestCase


class VoiceContextTrackingTests(BaseAPITestCase):
    """build_patient_context AI kuzatuv hisobotini o'z ichiga oladi"""

    def test_context_includes_fresh_tracking_report(self):
        """Bugungi hisobot kontekstga kiradi (xulosa + intizom %)"""
        user = self.create_patient(full_name="Karim Toshmatov")
        AITrackingReport.objects.create(
            patient=user,
            period_start=timezone.localdate(),
            period_end=timezone.localdate(),
            summary="Muolajalar yaxshi bajarildi.",
            adherence_percent=85,
            severity=AITrackingReport.Severity.NORMAL,
        )
        ctx = build_patient_context(user)
        self.assertIn("AI kuzatuv", ctx)
        self.assertIn("Muolajalar yaxshi bajarildi.", ctx)
        self.assertIn("85%", ctx)

    def test_critical_report_adds_doctor_reminder(self):
        """JIDDIY hisobot — shifokorga yo'naltirish eslatmasi qo'shiladi"""
        user = self.create_patient(full_name="Karim Toshmatov")
        AITrackingReport.objects.create(
            patient=user,
            period_start=timezone.localdate(),
            period_end=timezone.localdate(),
            summary="Bosim juda yuqori chiqdi.",
            severity=AITrackingReport.Severity.CRITICAL,
        )
        ctx = build_patient_context(user)
        self.assertIn("JIDDIY", ctx)
        self.assertIn("shifokorga", ctx)

    def test_stale_report_excluded(self):
        """3+ kun oldingi hisobot kontekstga KIRMAYDI"""
        user = self.create_patient(full_name="Karim Toshmatov")
        old = timezone.localdate() - timezone.timedelta(days=5)
        AITrackingReport.objects.create(
            patient=user,
            period_start=old,
            period_end=old,
            summary="Eski hisobot.",
            severity=AITrackingReport.Severity.NORMAL,
        )
        ctx = build_patient_context(user)
        self.assertNotIn("Eski hisobot", ctx)
