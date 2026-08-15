"""Excel fayldan Drug yozuvlarini import qilish helperi.

Management command (`python manage.py import_drugs`) va admin API (`POST
/pharmacy/drugs/import/`) ikkalasi ham shu funksiyani chaqiradi — xls
parsing logikasi bitta joyda.

Performance: oldin har row uchun `update_or_create()` chaqirilardi — 5000
row'li fayl uchun 5000 ta alohida DB roundtrip (prod Postgres alohida
server'da, har query ~5ms → ~25s). Daphne timeout'ga uchrar edi.

Endi batch: 3 ta SQL query — SELECT existing, bulk_create new,
filter().update() existing — har file uchun. Network roundtrip kam,
katta fayllar ham ~1-2s da tugaydi.
"""

from django.db import transaction

from app.pharmacy.models import Drug
from app.pharmacy.search import normalize_for_search


def import_drugs_from_xls(
    path: str,
    *,
    category: str,
    is_active: bool,
    dry_run: bool = False,
    name_col: int = 1,
) -> dict:
    """Xls fayldan Drug yozuvlarini idempotent import qiladi.

    `(category, name)` unique — mavjudlari yangilanadi (idempotent re-run).

    Strategiya (batch):
        1. Excel'ni o'qib, unique nomlar to'plamini yig'ish (RAM'da).
        2. Bitta SQL: shu kategoriyada qaysi nomlar allaqachon bor.
        3. Yangilarini `bulk_create` (1 SQL).
        4. Eskilarini `filter(...).update(is_active=, source=)` (1 SQL) —
           defaults qiymatlari yangilanadi (xuddi `update_or_create` kabi).

    Args:
        path: `.xls` fayl yo'li
        category: `Drug.Category` qiymati ("drug" | "substance" | ...)
        is_active: Yangi va eski yozuvlar uchun. Annul fayllarda False.
        dry_run: True — saqlamasdan faqat sanaydi
        name_col: Excel ustunidagi `name` indeksi (default 1)

    Returns:
        {"total", "created", "updated", "skipped", "errors": [{"row", "error"}, ...]}
    """
    import xlrd  # lazy — xlrd o'rnatilmagan serverlar uchun start-up'ni partlatmasin

    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)

    # === 1-bosqich: faylni RAM'ga o'qib chiqish ===
    # Headers row 1'da, ma'lumotlar 2-qatordan boshlanadi (0-qator title bloki).
    rows: list[tuple[int, str]] = []  # (row_idx, name)
    errors: list[dict] = []
    skipped = 0
    seen_names: set[str] = set()

    for row_idx in range(2, sheet.nrows):
        try:
            name = str(sheet.cell_value(row_idx, name_col)).strip()
        except IndexError:
            errors.append({"row": row_idx, "error": "ustun yo'q"})
            continue

        if not name:
            skipped += 1
            continue

        # Excel'da bir xil nom ikki marta uchrashi mumkin — birinchisini olamiz
        if name in seen_names:
            skipped += 1
            continue
        seen_names.add(name)
        rows.append((row_idx, name))

    total = len(rows) + skipped + len(errors)

    if dry_run:
        return {
            "total": total,
            "created": len(rows),
            "updated": 0,
            "skipped": skipped,
            "errors": errors,
        }

    # === 2-bosqich: mavjud yozuvlarni topish (1 SQL) ===
    all_names = [name for _, name in rows]
    existing_names = set(
        Drug.objects.filter(category=category, name__in=all_names).values_list(
            "name", flat=True
        )
    )

    # === 3-bosqich: yangi va eski ro'yxatlarga ajratish ===
    new_drugs: list[Drug] = []
    for _, name in rows:
        if name in existing_names:
            continue  # update bosqichida
        new_drugs.append(
            Drug(
                category=category,
                name=name,
                name_normalized=normalize_for_search(name),
                is_active=is_active,
                source=Drug.Source.IMPORT,
            )
        )

    # === 4-bosqich: atomic da bulk_create + bulk update ===
    created = 0
    with transaction.atomic():
        if new_drugs:
            # `ignore_conflicts=True` xavfsiz: parallel import qilinsa
            # IntegrityError'siz davom etadi. `batch_size` Postgres
            # query params chegarasini buzmaslik uchun.
            Drug.objects.bulk_create(new_drugs, batch_size=500, ignore_conflicts=True)

            # `ignore_conflicts=True` bo'lgani uchun len(new_drugs) created sonini
            # oshirib ko'rsatishi mumkin (parallel import 2-bosqich SELECT va
            # bulk_create orasida ayni nomni yaratib ulgursa). Haqiqiy created —
            # `(category, name)` bo'yicha DB'da hozir mavjud, lekin import oldidan
            # mavjud bo'lmagan yozuvlar soni.
            new_names = [d.name for d in new_drugs]
            now_existing = set(
                Drug.objects.filter(
                    category=category, name__in=new_names
                ).values_list("name", flat=True)
            )
            created = len(now_existing - existing_names)

        # Eskilar — defaults qiymatlarini yangilash (xuddi update_or_create
        # `defaults` kabi). 1 SQL bilan barchasini.
        if existing_names:
            Drug.objects.filter(
                category=category, name__in=existing_names
            ).update(is_active=is_active, source=Drug.Source.IMPORT)

    return {
        "total": total,
        "created": created,
        "updated": len(existing_names),
        "skipped": skipped,
        "errors": errors,
    }
