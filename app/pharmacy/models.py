from django.conf import settings
from django.db import models

from app.pharmacy.search import normalize_for_search


class Drug(models.Model):
    """Dorilar va tibbiy buyumlar yagona katalogi.

    O'zbekiston Sog'liqni saqlash vazirligi nashr etgan ro'yxatidan import
    qilinadi (Excel `.xls`). Admin paneldan qo'lda ham qo'shiladi.

    Soddalashtirilgan model: faqat tur (`category`) va nom (`name`) saqlanadi.
    Boshqa metama'lumotlar (forma, mamlakat, ATX kodi, va h.k.) ushbu MVP'da
    saqlanmaydi — kelajakda kerak bo'lsa qo'shiladi.
    """

    class Category(models.TextChoices):
        DRUG = "drug", "Dori vositasi"
        SUBSTANCE = "substance", "Substansiya"
        IN_VIVO = "in_vivo", "In vivo diagnostika"
        MED_DEVICE = "med_device", "Tibbiy texnika"
        IN_VITRO = "in_vitro", "In vitro diagnostika"

    class Source(models.TextChoices):
        IMPORT = "import", "Excel'dan import"
        MANUAL = "manual", "Admin qo'lda kiritgan"

    category = models.CharField(
        max_length=20, choices=Category.choices, db_index=True
    )
    name = models.TextField(
        db_index=True,
        help_text="Savdo nomi (Kirill + Lotin birga, ro'yxatdagidek)",
    )
    # Search uchun — Kirill ham, Lotin ham bir xil topiladi. `save()` da
    # `name`'dan avtomatik to'ldiriladi.
    name_normalized = models.TextField(db_index=True, blank=True)

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Annulirovannye (bekor qilingan) yozuvlar uchun False",
    )
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.IMPORT
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        # Bir kategoriya ichida nom takrorlanmaydi (idempotent import uchun ham
        # foydali). Tibbiy texnika va dorilar bir xil nomli bo'lishi mumkin —
        # shu sababli `(category, name)` unique.
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"], name="pharmacy_drug_uniq_cat_name"
            ),
        ]
        indexes = [
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self):
        short = (self.name or "").splitlines()[0][:60]
        return f"[{self.get_category_display()}] {short}"

    def save(self, *args, **kwargs):
        self.name_normalized = normalize_for_search(self.name or "")
        super().save(*args, **kwargs)


class DrugImportLog(models.Model):
    """Excel import auditi — admin'lar import tarixini kuzata oladi."""

    filename = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=Drug.Category.choices)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_imports",
    )
    total_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    is_active_default = models.BooleanField(
        default=True,
        help_text="Annulled fayl bo'lsa False — yozuvlar is_active=False yaratiladi",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} ({self.category}) — {self.created_at:%Y-%m-%d}"
