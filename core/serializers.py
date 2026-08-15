"""Umumiy serializer mixinlari.

i18n uchun: model'da `name = JSONField()` shaklida saqlangan
`{"uz": "...", "ru": "...", "cyr": "..."}` qiymatdan so'rov tiliga qarab
mos qiymatni qaytaradi (mobile/web ro'yxat o'qiganda) yoki to'liq JSON'ni
admin uchun (CRUD form'da). Yozish: admin doim 3 tilning hammasini yuboradi.
"""

from __future__ import annotations

from typing import Any, Iterable

from rest_framework import serializers

from core.i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    get_request_lang,
    normalize_translations,
    pick_translation,
)

# Boolean query param'larni bir xil parse qilish uchun
_TRUTHY = {"1", "true", "yes", "on"}


def _parse_bool(value) -> bool:
    """Query param qiymatini boolean'ga aylantiradi ('1'/'true'/'yes'/'on')."""
    return str(value).strip().lower() in _TRUTHY


class TranslatableFieldsMixin:
    """Translatable JSON field'larni `?lang=` ga qarab pyatakli string qiladi.

    Foydalanish:
        class SpecialtySerializer(TranslatableFieldsMixin, ModelSerializer):
            translatable_fields = ["name"]
            class Meta:
                model = Specialty
                fields = ["id", "name", "icon"]

    O'qish (GET):
        - `?lang=ru` bo'lsa → `name` ruschasi qaytariladi (string)
        - Til topilmasa fallback: `uz` → birinchi mavjud qiymat

    Yozish (POST/PATCH):
        - Admin to'g'ridan-to'g'ri dict yuboradi: `{"name": {"uz": "...", "ru": "...", "cyr": "..."}}`
        - Mavjud dict bilan validate qilinadi (normalize_translations)
        - Mobile/web mijozlardan dict YUBORILMAYDI — ular faqat o'qiydi
    """

    # Subclass override qiladi
    translatable_fields: Iterable[str] = ()

    # Admin uchun: GET'da `?include_translations=1` bo'lsa to'liq JSON qaytariladi
    # (form'da 3 ta input uchun)
    _admin_query_param = "include_translations"

    # --- Read ---

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not request:
            return data

        # Admin tahrir form'i uchun to'liq JSON kerak. List response'da
        # `to_representation` har object uchun chaqiriladi — `include_translations`
        # flag bir marta hisoblanib context'da cache'lanadi.
        include_full = self.context.get("_include_translations")
        if include_full is None:
            params = getattr(request, "query_params", None) or getattr(request, "GET", {})
            include_full = _parse_bool(params.get(self._admin_query_param))
            self.context["_include_translations"] = include_full

        if include_full:
            for field in self.translatable_fields:
                raw = getattr(instance, field, None)
                data[field] = normalize_translations(raw)
            return data

        # Oddiy o'qish — bitta tilga qisqartirish
        lang = get_request_lang(request)
        for field in self.translatable_fields:
            raw = getattr(instance, field, None)
            data[field] = pick_translation(raw, lang)
        return data

    # --- Write ---

    def to_internal_value(self, data):
        # Translatable field'lar string, list yoki dict sifatida kelishi mumkin:
        # - Admin form: dict {"uz": "...", "ru": "...", "cyr": "..."}
        # - String shortcut: "Kardiolog" — `{"uz": "Kardiolog"}` ga aylantiramiz
        # - List shortcut: ["chat", "voice"] — `{"uz": ["chat", "voice"]}` ga
        if isinstance(data, dict):
            data = dict(data)  # mutable copy
            for field in self.translatable_fields:
                if field not in data:
                    continue
                value = data[field]
                if isinstance(value, str):
                    data[field] = {DEFAULT_LANG: value}
                elif isinstance(value, list):
                    data[field] = {DEFAULT_LANG: value}
                elif isinstance(value, dict):
                    # Tilga noma'lum kalitlarni olib tashlaymiz
                    data[field] = {
                        k: v for k, v in value.items() if k in SUPPORTED_LANGS
                    }
                # Boshqa turlar — DRF o'zi xato beradi
        return super().to_internal_value(data)


class TranslatableJSONField(serializers.JSONField):
    """DRF JSONField'ning ozgina kengaytirilgan varianti.

    OpenAPI schema'da 3 tilli dict ekanligi ko'rinishi va xato xabarlari
    aniqlash uchun ishlatilishi mumkin. Hozir validate faqat:
    - dict bo'lishi shart
    - kalit faqat `SUPPORTED_LANGS` ichidan
    - bo'sh emas (kamida bitta til to'ldirilgan)
    """

    def to_internal_value(self, data: Any):
        if isinstance(data, str):
            data = {DEFAULT_LANG: data}
        if not isinstance(data, dict):
            self.fail("invalid")
        clean = {k: v for k, v in data.items() if k in SUPPORTED_LANGS}
        if not any(v.strip() for v in clean.values() if isinstance(v, str)):
            raise serializers.ValidationError(
                "Kamida bitta til to'ldirilishi shart."
            )
        return clean
