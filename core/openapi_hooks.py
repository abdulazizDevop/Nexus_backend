"""drf-spectacular postprocessing hook'lari.

`TranslatableFieldsMixin` subclass'larining `translatable_fields` ro'yxatidagi
maydonlarni OpenAPI schema'da `oneOf [string, object]` ga aylantiradi. Sababi:

- Backend modellarda bu maydonlar `JSONField` (`{"uz": "...", "ru": "..."}`)
- Lekin oddiy `?lang=` so'rovida client `string` qaytadi (TranslatableFieldsMixin
  to_representation orqali). Default OpenAPI schema `JSONField` → `object`
  ko'rsatadi — client uchun chalg'ituvchi.
- `?include_translations=1` (admin form) bilan object qaytadi → oneOf ikkala
  rejimni ham to'g'ri tasvirlaydi.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _translatable_serializers():
    """Loaded TranslatableFieldsMixin subclass'larini iteratsiya qiladi.

    rest_framework.serializers'da get_serializer_class chaqirish murakkab —
    barcha import qilingan klasslarni Python'ning class registry'idan
    olib chiqamiz.
    """
    from core.serializers import TranslatableFieldsMixin

    # Generator: barcha subclass va ularning nasllari
    def walk(cls):
        yield cls
        for sub in cls.__subclasses__():
            yield from walk(sub)

    for cls in walk(TranslatableFieldsMixin):
        if cls is TranslatableFieldsMixin:
            continue
        # Faqat translatable_fields belgilangan klasslar
        fields = getattr(cls, "translatable_fields", None)
        if fields:
            yield cls, tuple(fields)


def _schema_for_translatable_field() -> dict:
    """Translatable maydon uchun ikki rejimli schema.

    - Default rejim (`?lang=...` yoki standart): string qaytadi.
    - Admin rejim (`?include_translations=1`): `{uz, ru, cyr}` object qaytadi.

    `oneOf` ikkalasini ham OpenAPI tomonidan to'g'ri ifodalaydi.
    """
    return {
        "oneOf": [
            {
                "type": "string",
                "description": "User tilidagi qiymat (default rejim)",
            },
            {
                "type": "object",
                "description": (
                    "Admin rejim — `?include_translations=1` so'ralganda. "
                    "Har til alohida kalit (uz/ru/cyr)."
                ),
                "properties": {
                    "uz": {"type": "string"},
                    "ru": {"type": "string"},
                    "cyr": {"type": "string"},
                },
            },
        ],
    }


def _component_name_candidates(cls) -> list[str]:
    """Serializer class'idan OpenAPI komponent nomini taxminlash.

    drf-spectacular conventional naming:
      `MySerializer` → `My`
      `MyCreateSerializer` → `MyCreate` (yoki `PatchedMyCreate` update'da)
    """
    name = cls.__name__
    if name.endswith("Serializer"):
        name = name[: -len("Serializer")]
    return [name, f"Patched{name}"]


def annotate_translatable_fields(result, generator, request, public):
    """drf-spectacular POSTPROCESSING_HOOKS hooki.

    `result` — OpenAPI dict (komponent va path'lar). Hook walk qilib,
    har TranslatableFieldsMixin serializer'idan kelgan komponentdagi
    `translatable_fields` larni mos schema'ga (oneOf string/object)
    moslashtiradi.
    """
    components = result.get("components", {}).get("schemas", {})
    if not components:
        return result

    translatable_schema = _schema_for_translatable_field()
    annotated = 0
    for cls, fields in _translatable_serializers():
        for comp_name in _component_name_candidates(cls):
            comp = components.get(comp_name)
            if not comp or "properties" not in comp:
                continue
            for field in fields:
                if field in comp["properties"]:
                    comp["properties"][field] = dict(translatable_schema)
                    annotated += 1

    if annotated:
        logger.info(
            "OpenAPI: %d ta translatable field schema'si yangilandi", annotated
        )
    return result
