"""Universal i18n tarjima command — barcha translatable maydonlarni 3 tilga to'ldiradi.

Ro'yxatdagi modellar (app_label.Model.field1,field2,...) bo'yicha mavjud
yozuvlarning bo'sh tilarini Gemini orqali tarjima qiladi.

Ishlatish:
    # Default ro'yxat — barcha tanigan modellar
    python manage.py translate_existing

    # Faqat bitta model
    python manage.py translate_existing --only doctors.Specialty.name

    # Force — mavjud tarjimalarni qayta yaratish
    python manage.py translate_existing --force

    # Throttle Gemini chaqiruvlari orasidagi pauza (default 0.5s)
    python manage.py translate_existing --throttle 1.0

    # Sinov rejimi — saqlamasdan ko'rish
    python manage.py translate_existing --dry-run
"""

import time
from typing import Iterable

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from core.i18n import SUPPORTED_LANGS
from services.translate import auto_translate_all


# Mediik'da hozircha translatable model/maydon ro'yxati.
# Yangi qo'shilganida shu yerga yozish kerak.
DEFAULT_TARGETS: list[tuple[str, str, list[str]]] = [
    # (app_label, model_name, [field_names])
    ("doctors", "Specialty", ["name"]),
    ("health_packages", "HealthIndicatorType", ["name"]),
    ("payments", "ProPlan", ["name"]),
    ("payments", "ProFeatureFlag", ["label", "description"]),
    ("payments", "DoctorTariff", ["name", "description", "discount_label"]),
    # FAZA I — Analiz katalogi
    ("medical", "AnalysisType", ["name", "description"]),
    ("medical", "AnalysisIndicator", ["name"]),
    ("medical", "AnalysisPreparation", ["title", "description"]),
    # Eslatma: DoctorTariff.features — array per language. Auto-tarjima
    # qilish murakkab (har element alohida tarjima). Hozircha skip.
]


def _detect_source_lang(value: dict) -> str | None:
    """Dict ichidan birinchi non-empty tilni manba sifatida tanlash."""
    if not isinstance(value, dict):
        return None
    for lang in ("uz", "cyr", "ru"):  # uz birinchi (transliteratsiya tezroq)
        if value.get(lang):
            return lang
    return None


class Command(BaseCommand):
    help = "Translatable maydonlarni 3 tilga avtomatik tarjima qiladi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            type=str,
            help="Faqat bitta target: `app.Model.field1,field2,...`",
        )
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
        parser.add_argument(
            "--audit",
            action="store_true",
            help="Faqat 3 tilga to'lmagan yozuvlarni hisoblash, tarjima "
                 "qilmasdan. Nightly cron va manual tekshiruv uchun.",
        )

    def handle(self, *args, **opts):
        targets = self._parse_targets(opts.get("only"))

        if opts.get("audit"):
            self._audit(targets)
            return

        force = opts["force"]
        dry = opts["dry_run"]
        throttle = opts["throttle"]

        for app_label, model_name, fields in targets:
            try:
                Model = apps.get_model(app_label, model_name)
            except LookupError:
                self.stdout.write(
                    self.style.WARNING(f"  Model topilmadi: {app_label}.{model_name}")
                )
                continue

            self._translate_model(
                Model, fields, force=force, dry=dry, throttle=throttle
            )

        self.stdout.write(self.style.SUCCESS("\nHammasi tugadi"))

    # --- Audit ---

    def _audit(self, targets):
        """3 tilga to'lmagan yozuvlarni hisoblash + qisqacha hisobot.

        Output:
            doctors.Specialty.name:
              total=9, missing=2 (id=4 ru bo'sh; id=7 cyr bo'sh)
        """
        total_missing = 0
        for app_label, model_name, fields in targets:
            try:
                Model = apps.get_model(app_label, model_name)
            except LookupError:
                continue
            label = f"{app_label}.{model_name}"
            total = Model.objects.count()
            missing_records = []

            for obj in Model.objects.all().iterator(chunk_size=500):
                gaps = []
                for field in fields:
                    raw = getattr(obj, field, None)
                    if not isinstance(raw, dict):
                        continue
                    missing_langs = [
                        lang for lang in SUPPORTED_LANGS if not raw.get(lang)
                    ]
                    if missing_langs:
                        gaps.append(f"{field}({','.join(missing_langs)})")
                if gaps:
                    missing_records.append((obj.id, gaps))

            self.stdout.write(
                self.style.NOTICE(
                    f"\n{label}: total={total}, missing={len(missing_records)}"
                )
            )
            for obj_id, gaps in missing_records[:10]:
                self.stdout.write(f"  #{obj_id}: {' | '.join(gaps)}")
            if len(missing_records) > 10:
                self.stdout.write(f"  ... +{len(missing_records) - 10} ta")
            total_missing += len(missing_records)

        if total_missing == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ Hammasi 3 tilga to'lgan"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"\nJami {total_missing} ta yozuv tarjimaga muhtoj. "
                    "Tarjima qilish: shu command --audit'siz."
                )
            )

    # --- Helpers ---

    def _parse_targets(self, only: str | None) -> list[tuple[str, str, list[str]]]:
        if not only:
            return DEFAULT_TARGETS
        # `doctors.Specialty.name,icon` formatda
        try:
            head, fields_str = only.rsplit(".", 1)
            app_label, model_name = head.split(".", 1)
        except ValueError:
            raise CommandError(
                "--only format: app.Model.field1[,field2,...] "
                "(masalan: doctors.Specialty.name)"
            )
        fields = [f.strip() for f in fields_str.split(",") if f.strip()]
        return [(app_label, model_name, fields)]

    def _translate_model(
        self,
        Model,
        fields: Iterable[str],
        *,
        force: bool,
        dry: bool,
        throttle: float,
    ):
        # iterator(chunk_size=500) — kelajakda Pharmacy/Drug 13k+ yozuv
        # bo'lganda OOM oldini olish uchun. Har yozuv alohida DB cursor'dan
        # keladi va alohida atomic obj.save() bilan saqlanadi.
        label = f"{Model._meta.app_label}.{Model.__name__}"
        total = Model.objects.count()
        self.stdout.write(
            self.style.NOTICE(
                f"\n=== {label} ({total} yozuv, fields={list(fields)}) ==="
            )
        )

        fields_list = list(fields)
        for obj in Model.objects.all().iterator(chunk_size=500):
            updated = False
            for field in fields_list:
                raw = getattr(obj, field, None)
                if not isinstance(raw, dict):
                    continue

                source_lang = _detect_source_lang(raw)
                if not source_lang:
                    continue  # hammasi bo'sh

                source_text = raw[source_lang]
                if not isinstance(source_text, str) or not source_text.strip():
                    continue  # source string emas (masalan list — features)

                # 3 tildan bittasi bo'sh bo'lsa yoki force=True
                needs_translate = force or not all(
                    raw.get(lang) for lang in SUPPORTED_LANGS
                )
                if not needs_translate:
                    continue

                try:
                    translated = auto_translate_all(source_text, source_lang)
                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(f"  #{obj.id} {field} xato: {exc}")
                    )
                    continue

                new_value = dict(raw)
                for lang in SUPPORTED_LANGS:
                    if force or not new_value.get(lang):
                        new_value[lang] = translated.get(lang, "")

                setattr(obj, field, new_value)
                updated = True

                self.stdout.write(
                    f"  #{obj.id} {field}: {source_text!r} → "
                    f"uz={new_value.get('uz')!r}, "
                    f"ru={new_value.get('ru')!r}, "
                    f"cyr={new_value.get('cyr')!r}"
                )

                # Gemini rate limit'ga ortiqcha bosim bermaslik
                time.sleep(throttle)

            if updated and not dry:
                obj.save(update_fields=fields_list)
