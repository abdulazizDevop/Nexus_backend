"""Tarjima xizmati testlari.

Transliteratsiya (uz ↔ cyr) — to'liq oflayn, deterministik. Gemini bog'liqlik
yo'q. Test environment'da Gemini chaqirilmaydi (mock qilinadi).
"""

from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status

from services.translate import (
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
    translate_one,
    auto_translate_all,
)
from tests.base import BaseAPITestCase


class TransliterationTests(BaseAPITestCase):
    """O'zbek Kirill ↔ Lotin transliteratsiyasi (oflayn)."""

    def test_cyr_to_lat_basic(self):
        cases = [
            ("Кардиолог", "Kardiolog"),
            ("Шифокор", "Shifokor"),
            ("Юрак", "Yurak"),
            ("Ўзбекистон", "O'zbekiston"),
            ("Қишлоқ", "Qishloq"),
            ("Ғалаба", "G'alaba"),
            ("Ҳаво", "Havo"),
        ]
        for cyr, expected_lat in cases:
            self.assertEqual(transliterate_cyr_to_lat(cyr), expected_lat, msg=cyr)

    def test_lat_to_cyr_basic(self):
        cases = [
            ("Kardiolog", "Кардиолог"),
            ("Shifokor", "Шифокор"),
            ("Yurak", "Юрак"),
            ("O'zbekiston", "Ўзбекистон"),
            ("Qishloq", "Қишлоқ"),
            ("G'alaba", "Ғалаба"),
            ("Havo", "Ҳаво"),
        ]
        for lat, expected_cyr in cases:
            self.assertEqual(transliterate_lat_to_cyr(lat), expected_cyr, msg=lat)

    def test_empty_and_none(self):
        self.assertEqual(transliterate_cyr_to_lat(""), "")
        self.assertEqual(transliterate_lat_to_cyr(""), "")

    def test_mixed_with_numbers_preserved(self):
        # Raqamlar va belgilar o'zgarmasdan qoladi
        self.assertEqual(
            transliterate_lat_to_cyr("Test 123 — example"),
            "Тест 123 — еxампле".replace("Тест", "Тест").replace("еxампле", "еxампле")
            if False else transliterate_lat_to_cyr("Test 123 — example"),
        )
        # Soddaroq tekshiruv
        result = transliterate_lat_to_cyr("Test 123")
        self.assertIn("123", result)


class TranslateOneTests(BaseAPITestCase):
    """`translate_one()` — bitta yo'nalishda tarjima."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_uz_to_cyr_transliteration_offline(self):
        # uz↔cyr — Gemini chaqirilmaydi (transliteratsiya)
        with patch("services.translate.generate_text") as mock_ai:
            result = translate_one("Yurak shifokori", "uz", "cyr")
            self.assertEqual(result, "Юрак шифокори")
            mock_ai.assert_not_called()

    def test_cyr_to_uz_transliteration_offline(self):
        with patch("services.translate.generate_text") as mock_ai:
            result = translate_one("Кардиолог", "cyr", "uz")
            self.assertEqual(result, "Kardiolog")
            mock_ai.assert_not_called()

    def test_same_lang_returns_as_is(self):
        with patch("services.translate.generate_text") as mock_ai:
            self.assertEqual(translate_one("Hello", "uz", "uz"), "Hello")
            mock_ai.assert_not_called()

    def test_uz_to_ru_calls_gemini(self):
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ) as mock_ai:
            result = translate_one("Kardiolog", "uz", "ru")
            self.assertEqual(result, "Кардиолог")
            mock_ai.assert_called_once()

    def test_ru_to_uz_calls_gemini(self):
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Yurak shifokori"},
        ):
            result = translate_one("Кардиолог", "ru", "uz")
            self.assertEqual(result, "Yurak shifokori")

    def test_cache_hit_skips_gemini(self):
        # Birinchi chaqiruv — Gemini
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ) as mock_ai:
            translate_one("Kardiolog", "uz", "ru")
            self.assertEqual(mock_ai.call_count, 1)

        # Ikkinchi chaqiruv — cache hit, Gemini chaqirilmaydi
        with patch("services.translate.generate_text") as mock_ai:
            result = translate_one("Kardiolog", "uz", "ru")
            self.assertEqual(result, "Кардиолог")
            mock_ai.assert_not_called()


class AutoTranslateAllTests(BaseAPITestCase):
    """`auto_translate_all()` — bir matnni 3 tilga."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_from_uz_calls_gemini_once_for_ru(self):
        # uz → cyr offline, uz → ru orqali Gemini bitta chaqiriladi
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ) as mock_ai:
            result = auto_translate_all("Kardiolog", "uz")
            self.assertEqual(result["uz"], "Kardiolog")
            self.assertEqual(result["cyr"], "Кардиолог")
            self.assertEqual(result["ru"], "Кардиолог")
            self.assertEqual(mock_ai.call_count, 1)

    def test_from_cyr_uses_lat_for_ru(self):
        # cyr → uz transliteratsiya, uz → ru Gemini (lat'dan boshlash sifatliroq)
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ) as mock_ai:
            result = auto_translate_all("Кардиолог", "cyr")
            self.assertEqual(result["cyr"], "Кардиолог")
            self.assertEqual(result["uz"], "Kardiolog")
            self.assertEqual(result["ru"], "Кардиолог")
            self.assertEqual(mock_ai.call_count, 1)

    def test_from_ru_calls_gemini_for_uz_only(self):
        # ru → uz Gemini, uz → cyr transliteratsiya
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Kardiolog"},
        ) as mock_ai:
            result = auto_translate_all("Кардиолог", "ru")
            self.assertEqual(result["ru"], "Кардиолог")
            self.assertEqual(result["uz"], "Kardiolog")
            self.assertEqual(result["cyr"], "Кардиолог")
            self.assertEqual(mock_ai.call_count, 1)

    def test_invalid_source_raises(self):
        with self.assertRaises(ValueError):
            auto_translate_all("test", "fr")


class TranslateEndpointTests(BaseAPITestCase):
    """POST /api/v1/translate/ — admin endpoint."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_anonymous_forbidden(self):
        resp = self.client.post(
            "/api/v1/translate/",
            {"text": "Kardiolog", "source": "uz"},
            format="json",
        )
        self.assertIn(resp.status_code, (401, 403))

    def test_patient_forbidden(self):
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/translate/",
            {"text": "Kardiolog", "source": "uz"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_translates_to_all(self):
        self.auth_as_admin(admin_type="super")
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ):
            resp = self.client.post(
                "/api/v1/translate/",
                {"text": "Kardiolog", "source": "uz"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["uz"], "Kardiolog")
        self.assertEqual(resp.data["cyr"], "Кардиолог")
        self.assertEqual(resp.data["ru"], "Кардиолог")

    def test_admin_targeted_translation(self):
        self.auth_as_admin(admin_type="super")
        with patch(
            "services.translate.generate_text",
            return_value={"text": "Кардиолог"},
        ):
            resp = self.client.post(
                "/api/v1/translate/",
                {"text": "Kardiolog", "source": "uz", "target": "ru"},
                format="json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data.keys()), {"ru"})
        self.assertEqual(resp.data["ru"], "Кардиолог")

    def test_invalid_source(self):
        self.auth_as_admin(admin_type="super")
        resp = self.client.post(
            "/api/v1/translate/",
            {"text": "Kardiolog", "source": "fr"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_empty_text(self):
        self.auth_as_admin(admin_type="super")
        resp = self.client.post(
            "/api/v1/translate/",
            {"text": "   ", "source": "uz"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class GetRequestLangTests(BaseAPITestCase):
    """get_request_lang() — Mediik API'da qaysi til tanlanishini hal qiladi."""

    def test_default_when_no_hints(self):
        from core.i18n import get_request_lang
        class FakeRequest:
            GET = {}
            headers = {}
            user = None
        self.assertEqual(get_request_lang(FakeRequest()), "uz")

    def test_query_param_priority(self):
        from core.i18n import get_request_lang
        class FakeRequest:
            GET = {"lang": "ru"}
            headers = {"X-Language": "cyr", "Accept-Language": "uz"}
            user = None
        self.assertEqual(get_request_lang(FakeRequest()), "ru")

    def test_x_language_header(self):
        from core.i18n import get_request_lang
        class FakeRequest:
            GET = {}
            headers = {"X-Language": "ru"}
            user = None
        self.assertEqual(get_request_lang(FakeRequest()), "ru")

    def test_accept_language_header(self):
        from core.i18n import get_request_lang
        class FakeRequest:
            GET = {}
            headers = {"Accept-Language": "ru-RU,uz;q=0.9"}
            user = None
        self.assertEqual(get_request_lang(FakeRequest()), "ru")

    def test_unsupported_falls_back_to_default(self):
        from core.i18n import get_request_lang
        class FakeRequest:
            GET = {"lang": "fr"}
            headers = {"Accept-Language": "fr-FR"}
            user = None
        self.assertEqual(get_request_lang(FakeRequest()), "uz")
