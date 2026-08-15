"""Excel'dan dorilarni import qilish.

Ishlatish:
    # Bitta fayl, aniq kategoriya
    python manage.py import_drugs --file dorilar/1.xls --category drug

    # Papkadan barchasi (fayl nomidan kategoriya avtomatik aniqlanadi)
    python manage.py import_drugs --folder dorilar/

    # `--dry-run` — saqlamasdan ko'rish
    python manage.py import_drugs --folder dorilar/ --dry-run

Idempotent: (category, name) unique, mavjud bo'lsa o'tkazib yuboriladi (skipped).
Annulirovan fayllar (6 va 7) — `is_active=False` bilan yaratiladi.
"""

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.pharmacy.importer import import_drugs_from_xls
from app.pharmacy.models import Drug, DrugImportLog


# Fayl nomi -> (category, is_active) ko'magi --folder rejimi uchun
FILENAME_PATTERNS = [
    # Bekor qilingan fayllar — is_active=False
    ("Аннул.лек", "drug", False),
    ("аннул.лек", "drug", False),
    ("annul.lek", "drug", False),
    ("Аннул.изделия", "med_device", False),
    ("аннул.изделия", "med_device", False),
    ("annul.izdel", "med_device", False),
    # Asosiylari — is_active=True
    ("Субстанция", "substance", True),
    ("субстанция", "substance", True),
    ("substansi", "substance", True),
    ("in vivo", "in_vivo", True),
    ("in_vivo", "in_vivo", True),
    ("Мед.техник", "med_device", True),
    ("мед.техник", "med_device", True),
    ("med.tex", "med_device", True),
    ("med_tex", "med_device", True),
    ("in vitro", "in_vitro", True),
    ("in_vitro", "in_vitro", True),
    ("ИМН", "in_vitro", True),  # IMN — In vitro
    ("imn", "in_vitro", True),
]


def _detect_from_filename(filename: str) -> tuple[str | None, bool]:
    """Fayl nomidan kategoriya va is_active'ni aniqlaydi.

    Aniqlay olmasa (None, True) qaytaradi — chaqiruvchi qaror qabul qiladi.
    """
    lower = filename.lower()
    for pattern, category, is_active in FILENAME_PATTERNS:
        if pattern.lower() in lower:
            return category, is_active
    # Aniq 1-fayl (asosiy)
    if filename.startswith("1.") or "лек.ср" in lower or "lek.sr" in lower:
        return "drug", True
    return None, True


class Command(BaseCommand):
    help = "Excel'dan Drug yozuvlarini import qilish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            help="Bitta `.xls` fayl yo'li",
        )
        parser.add_argument(
            "--folder",
            type=str,
            help="Papka — ichidagi barcha `.xls` fayllar import qilinadi",
        )
        parser.add_argument(
            "--category",
            type=str,
            choices=[c[0] for c in Drug.Category.choices],
            help="Kategoriya (--file bilan birga, --folder'da avtomatik)",
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help="Yaratilgan yozuvlarni is_active=False qilish (annulled)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Saqlamay, faqat hisoblab chiqib ko'rsatish",
        )

    def handle(self, *args, **opts):
        file_path = opts.get("file")
        folder = opts.get("folder")
        if not file_path and not folder:
            raise CommandError("--file yoki --folder yuboring")
        if file_path and not opts.get("category"):
            raise CommandError("--file uchun --category majburiy")

        targets: list[tuple[str, str, bool]] = []  # (path, category, is_active)

        if file_path:
            targets.append((file_path, opts["category"], not opts["inactive"]))
        else:
            for entry in sorted(os.listdir(folder)):
                if not entry.lower().endswith(".xls"):
                    continue
                full = os.path.join(folder, entry)
                cat, is_active = _detect_from_filename(entry)
                if cat is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ❓ Fayl tanilmadi, o'tkazildi: {entry}"
                        )
                    )
                    continue
                targets.append((full, cat, is_active))

        if not targets:
            self.stdout.write(self.style.WARNING("Import qilinadigan fayl yo'q"))
            return

        for path, category, is_active in targets:
            self._import_one(
                path=path,
                category=category,
                is_active=is_active,
                dry_run=opts["dry_run"],
            )

    def _import_one(
        self, *, path: str, category: str, is_active: bool, dry_run: bool
    ):
        filename = Path(path).name
        self.stdout.write(
            self.style.NOTICE(
                f"\n>>> Import: {filename} → category={category}, "
                f"is_active={is_active}, dry_run={dry_run}"
            )
        )

        try:
            result = import_drugs_from_xls(
                path, category=category, is_active=is_active, dry_run=dry_run
            )
        except ImportError:
            raise CommandError(
                "xlrd kerak: pip install xlrd. Yoki xlrd_legacy ishlatib ko'ring."
            )
        except Exception as e:
            raise CommandError(f"Faylni o'qib bo'lmadi: {e}")

        if not dry_run:
            DrugImportLog.objects.create(
                filename=filename,
                category=category,
                total_rows=result["total"],
                created_count=result["created"],
                updated_count=result["updated"],
                skipped_count=result["skipped"],
                error_count=len(result["errors"]),
                errors=result["errors"][:50],
                is_active_default=is_active,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"  total={result['total']} created={result['created']} "
                f"updated={result['updated']} skipped={result['skipped']} "
                f"errors={len(result['errors'])}"
            )
        )
        for err in result["errors"][:5]:
            self.stdout.write(self.style.ERROR(f"  ! {err}"))
