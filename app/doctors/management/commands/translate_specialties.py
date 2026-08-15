"""Mavjud Specialty.name yozuvlarini 3 tilga tarjima qilish.

Avval CharField → JSONField migratsiyasi (0011) eski `"Kardiolog"` string'ini
`{"uz": "Kardiolog"}` qilib o'zgartirgan. Bu command esa Gemini orqali
`ru` va `cyr` tilini ham qo'shadi.

Ishlatish:
    python manage.py translate_specialties              # hamma yozuvlar
    python manage.py translate_specialties --force      # mavjud tarjimalarni qayta yaratish
    python manage.py translate_specialties --dry-run    # nima qilinishini ko'rsatadi, saqlamaydi
"""

import time

from django.core.management.base import BaseCommand

from app.doctors.models import Specialty
from services.translate import auto_translate_all


class Command(BaseCommand):
    help = "Mavjud Specialty.name'larni 3 tilga avtomatik tarjima qiladi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Mavjud tarjimalarni ham qaytadan tarjima qilish",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Saqlamasdan, nima qilinishini ko'rsatadi",
        )
        parser.add_argument(
            "--throttle",
            type=float,
            default=0.5,
            help="Gemini chaqiruvlari orasidagi pauza (sekund). Default 0.5",
        )

    def handle(self, *args, **opts):
        force = opts["force"]
        dry = opts["dry_run"]
        throttle = opts["throttle"]

        items = list(Specialty.objects.all())
        self.stdout.write(
            self.style.NOTICE(
                f"Jami {len(items)} ta Specialty topildi. "
                f"force={force} dry_run={dry}"
            )
        )

        for sp in items:
            raw = sp.name or {}
            if not isinstance(raw, dict):
                # Bu nostandart holat — migration ishlamaganga o'xshaydi
                self.stdout.write(
                    self.style.WARNING(
                        f"  #{sp.id} name dict emas: {type(raw).__name__} → o'tkazib yuboriladi"
                    )
                )
                continue

            source_text = raw.get("uz") or raw.get("cyr") or raw.get("ru")
            if not source_text:
                self.stdout.write(
                    self.style.WARNING(f"  #{sp.id} bo'sh — o'tkazib yuboriladi")
                )
                continue

            # Manba til'ni aniqlash — qaysi til to'ldirilgan
            source_lang = "uz" if raw.get("uz") else "cyr" if raw.get("cyr") else "ru"

            # Force emas va 3 tilning hammasi to'ldirilgan bo'lsa — skip
            if not force and all(raw.get(lang) for lang in ("uz", "ru", "cyr")):
                self.stdout.write(f"  #{sp.id} {source_text!r} — allaqachon 3 tilda")
                continue

            try:
                translated = auto_translate_all(source_text, source_lang)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  #{sp.id} xato: {exc}")
                )
                continue

            # Faqat bo'sh tilarini yozish (force=True bo'lsa hammasi yangilanadi)
            new_value = dict(raw)
            for lang in ("uz", "ru", "cyr"):
                if force or not new_value.get(lang):
                    new_value[lang] = translated.get(lang, "")

            self.stdout.write(
                f"  #{sp.id} {source_text!r} → "
                f"uz={new_value.get('uz')!r}, "
                f"ru={new_value.get('ru')!r}, "
                f"cyr={new_value.get('cyr')!r}"
            )

            if not dry:
                sp.name = new_value
                sp.save(update_fields=["name"])

            # Gemini rate limit'ga ortiqcha bosim bermaslik uchun
            if source_lang == "ru" or source_lang == "uz":
                time.sleep(throttle)

        self.stdout.write(self.style.SUCCESS("Tugadi"))
