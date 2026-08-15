"""Audit FAZA A + FAZA I + Security fix testlari.

Bu testlar audit jarayonida topilgan bug'lar uchun yozilgan:
- FAZA A: production raw dict (plan_name, tariff_name, indicator_type.name)
- FAZA I: Analiz katalogi i18n (AnalysisType/Indicator/Preparation)
- Security: OTP cooldown, registration_token one-time use
"""

import time
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIRequestFactory

from app.auth.models import OTPCode
from app.medical.models import (
    AnalysisIndicator,
    AnalysisPreparation,
    AnalysisType,
)
from app.medical.serializers import AnalysisTypeSerializer
from core.i18n import pick_for, pick_translation
from tests.base import BaseAPITestCase


class PickTranslationTests(BaseAPITestCase):
    """`pick_translation` edge case'lari (FAZA F1 audit covered gap)."""

    def test_none(self):
        self.assertEqual(pick_translation(None, "uz"), "")

    def test_empty_dict(self):
        self.assertEqual(pick_translation({}, "uz"), {})

    def test_legacy_string(self):
        """Eski CharField data — string sifatida qaytadi."""
        self.assertEqual(pick_translation("Kardiolog", "ru"), "Kardiolog")

    def test_uz_present(self):
        raw = {"uz": "Kardiolog", "ru": "Кардиолог", "cyr": "Кардиолог"}
        self.assertEqual(pick_translation(raw, "ru"), "Кардиолог")
        self.assertEqual(pick_translation(raw, "uz"), "Kardiolog")

    def test_fallback_to_uz(self):
        """Ru bo'sh bo'lsa fallback `uz` ga."""
        raw = {"uz": "Kardiolog", "ru": "", "cyr": ""}
        self.assertEqual(pick_translation(raw, "ru"), "Kardiolog")

    def test_first_non_empty_fallback(self):
        """uz ham bo'sh bo'lsa birinchi non-empty."""
        raw = {"uz": "", "ru": "Кардиолог", "cyr": ""}
        self.assertEqual(pick_translation(raw, "uz"), "Кардиолог")


class PickForCacheTests(BaseAPITestCase):
    """`pick_for(context, raw)` context cache (hot path optimallashtirish)."""

    def test_lang_cached_in_context(self):
        """get_request_lang faqat bir marta chaqirilishi kerak."""
        from app.medical.models import AnalysisType
        AnalysisType.objects.create(
            name={"uz": "Qon", "ru": "Кровь", "cyr": "Қон"}, code="blood"
        )
        factory = APIRequestFactory()
        request = factory.get("/?lang=ru")
        ctx = {"request": request}

        # Birinchi chaqiruv lang ni resolve qiladi
        result1 = pick_for(ctx, {"uz": "X", "ru": "Y", "cyr": "Z"})
        self.assertEqual(result1, "Y")
        self.assertEqual(ctx.get("_resolved_lang"), "ru")

        # Ikkinchi chaqiruv cache'dan oladi
        result2 = pick_for(ctx, {"uz": "A", "ru": "B", "cyr": "C"})
        self.assertEqual(result2, "B")

    def test_no_context(self):
        """Context None bo'lsa default uz."""
        result = pick_for(None, {"uz": "Kardiolog", "ru": "Кардиолог"})
        self.assertEqual(result, "Kardiolog")


class AnalysisTypeI18nTests(BaseAPITestCase):
    """FAZA I — AnalysisType JSONField + TranslatableFieldsMixin."""

    def setUp(self):
        super().setUp()
        self.t = AnalysisType.objects.create(
            name={"uz": "Bioximik qon tahlili", "ru": "Биохимия крови", "cyr": "Биохимик қон таҳлили"},
            code="biochem",
            icon="🩸",
            description={"uz": "Och qoringa", "ru": "Натощак", "cyr": "Оч қорнга"},
        )
        self.factory = APIRequestFactory()

    def test_default_lang(self):
        """Default uz (X-Language yo'q)."""
        req = self.factory.get("/")
        data = AnalysisTypeSerializer(self.t, context={"request": req}).data
        self.assertEqual(data["name"], "Bioximik qon tahlili")
        self.assertEqual(data["description"], "Och qoringa")

    def test_lang_ru(self):
        """?lang=ru → ru qaytadi."""
        req = self.factory.get("/?lang=ru")
        data = AnalysisTypeSerializer(self.t, context={"request": req}).data
        self.assertEqual(data["name"], "Биохимия крови")
        self.assertEqual(data["description"], "Натощак")

    def test_lang_cyr(self):
        """?lang=cyr → cyr qaytadi."""
        req = self.factory.get("/?lang=cyr")
        data = AnalysisTypeSerializer(self.t, context={"request": req}).data
        self.assertEqual(data["name"], "Биохимик қон таҳлили")

    def test_xlanguage_header(self):
        """X-Language header — mobile uchun asosiy yondashuv."""
        req = self.factory.get("/", HTTP_X_LANGUAGE="ru")
        data = AnalysisTypeSerializer(self.t, context={"request": req}).data
        self.assertEqual(data["name"], "Биохимия крови")

    def test_include_translations(self):
        """?include_translations=1 — admin form uchun to'liq dict."""
        req = self.factory.get("/?include_translations=1")
        data = AnalysisTypeSerializer(self.t, context={"request": req}).data
        self.assertIsInstance(data["name"], dict)
        self.assertEqual(data["name"]["uz"], "Bioximik qon tahlili")
        self.assertEqual(data["name"]["ru"], "Биохимия крови")
        self.assertEqual(data["name"]["cyr"], "Биохимик қон таҳлили")

    def test_create_string_shortcut(self):
        """String input → `{uz: X}` ga aylantirish (admin convenience)."""
        ser = AnalysisTypeSerializer(
            data={"name": "Yangi tur", "code": "new_type"}
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        instance = ser.save()
        self.assertEqual(instance.name, {"uz": "Yangi tur"})


class AnalysisTypeNameForTests(BaseAPITestCase):
    """Analysis.type_name_for(user) - push notification matni uchun."""

    def test_user_with_ru_setting(self):
        from app.medical.models import Analysis
        from app.users.models import UserSettings

        atype = AnalysisType.objects.create(
            name={"uz": "Qon", "ru": "Кровь", "cyr": "Қон"}, code="blood"
        )
        user = self.create_patient()
        # UserSettings yaratish (signal default'i bilan bo'lmasa)
        settings, _ = UserSettings.objects.get_or_create(user=user)
        settings.language = "ru"
        settings.save()

        analysis = Analysis.objects.create(patient=user, type=atype)
        self.assertEqual(analysis.type_name_for(user), "Кровь")

    def test_user_without_settings_defaults_uz(self):
        from app.medical.models import Analysis

        atype = AnalysisType.objects.create(
            name={"uz": "Qon", "ru": "Кровь"}, code="blood"
        )
        user = self.create_patient()
        analysis = Analysis.objects.create(patient=user, type=atype)
        # UserSettings hali yaratilmagan (yoki tili yo'q)
        self.assertEqual(analysis.type_name_for(user), "Qon")


class OTPCooldownTests(BaseAPITestCase):
    """Audit C1 — per-phone OTP resend cooldown."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_cooldown_blocks_within_60s(self):
        """DEBUG=False bo'lganda 60s cooldown."""
        with patch("app.auth.models.settings") as mock_settings:
            mock_settings.DEBUG = False
            phone = "998901111111"
            ok, retry, reason = OTPCode.check_send_cooldown(phone)
            self.assertTrue(ok)
            OTPCode.mark_sent(phone)
            # Ikkinchi darrov — bloklangan
            ok, retry, reason = OTPCode.check_send_cooldown(phone)
            self.assertFalse(ok)
            self.assertEqual(reason, "cooldown")
            self.assertGreater(retry, 0)

    def test_daily_limit(self):
        """24h ichida 10 ta urinish o'tgach blocked."""
        with patch("app.auth.models.settings") as mock_settings:
            mock_settings.DEBUG = False
            phone = "998902222222"
            # 10 ta cache.set qilamiz (cooldown'ni bypass qilib)
            cache.set(f"otp:daily:{phone}", 10, timeout=86400)
            ok, retry, reason = OTPCode.check_send_cooldown(phone)
            self.assertFalse(ok)
            self.assertEqual(reason, "daily_limit")

    def test_debug_mode_bypass(self):
        """DEBUG=True da hech qanday limit yo'q."""
        with patch("app.auth.models.settings") as mock_settings:
            mock_settings.DEBUG = True
            phone = "998903333333"
            for _ in range(20):
                ok, _, _ = OTPCode.check_send_cooldown(phone)
                self.assertTrue(ok)


class OTPRaceConditionTests(BaseAPITestCase):
    """Audit C2 — verify atomic + select_for_update."""

    def test_verify_uses_select_for_update(self):
        """_consume_active_otp transaction.atomic ichida ishlaydi."""
        import inspect

        src = inspect.getsource(OTPCode._consume_active_otp)
        self.assertIn("select_for_update", src)
        self.assertIn("transaction.atomic", src)


class NotificationCatalogTests(BaseAPITestCase):
    """Audit FAZA D — push notification catalog."""

    def test_render_existing_key(self):
        """Catalogdagi kalit 3 til uchun render bo'ladi."""
        from app.notifications.catalog import render

        title, body = render(
            "tariff_approved",
            "ru",
            params={"tariff_name": "Премиум"},
        )
        self.assertEqual(title, "Тариф подтверждён")
        self.assertIn("Премиум", body)

    def test_render_uz_fallback(self):
        """Til topilmasa uz fallback."""
        from app.notifications.catalog import render

        title, body = render(
            "tariff_approved",
            "en",  # qo'llab-quvvatlanmagan
            params={"tariff_name": "Pro"},
        )
        self.assertEqual(title, "Tarif tasdiqlandi")

    def test_render_unknown_key(self):
        """Mavjud bo'lmagan kalit bo'sh string qaytaradi."""
        from app.notifications.catalog import render

        title, body = render("nonexistent_key", "uz")
        self.assertEqual(title, "")
        self.assertEqual(body, "")

    def test_render_missing_placeholder(self):
        """Yetishmagan {param} crash bo'lmaslik — shablonni qaytaradi."""
        from app.notifications.catalog import render

        title, body = render("tariff_approved", "uz", params={})
        # Shablon o'zicha qaytadi (KeyError yutilgan)
        self.assertIn("tariff_name", body)

    def test_all_keys_have_3_langs(self):
        """Har bir kalit uz/ru/cyr title+body bilan to'ldirilgan."""
        from app.notifications.catalog import NOTIFY_CATALOG

        for key, entry in NOTIFY_CATALOG.items():
            for field in ("title", "body"):
                bucket = entry.get(field) or {}
                for lang in ("uz", "ru", "cyr"):
                    self.assertIn(
                        lang, bucket,
                        f"{key}.{field} '{lang}' tili yo'q",
                    )
                    self.assertTrue(
                        bucket[lang],
                        f"{key}.{field}.{lang} bo'sh",
                    )

    def test_notify_by_key_uses_user_language(self):
        """notify_by_key user.settings.language ga qarab matn tanlaydi."""
        from app.notifications.models import Notification
        from app.notifications.utils import notify_by_key
        from app.users.models import UserSettings

        user = self.create_patient()
        settings, _ = UserSettings.objects.get_or_create(user=user)
        settings.language = "ru"
        settings.save()

        notif = notify_by_key(
            user,
            type=Notification.Type.TARIFF_APPROVED,
            key="tariff_approved",
            params={"tariff_name": "Премиум"},
            send_push=False,  # Test'da push yo'q
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "Тариф подтверждён")
        self.assertIn("Премиум", notif.body)
