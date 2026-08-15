from .common import *  # noqa: F401,F403 - header importlar + helperlar

class SystemSetting(models.Model):
    """Runtime-editable global config — admin paneldan boshqariladi.

    Misollar:
        key="doctor_commission_percent", value=15
        key="pro_trial_days", value=7
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"

    @classmethod
    def get(cls, key, default=None):
        obj = cls.objects.filter(key=key).first()
        return obj.value if obj else default

    @classmethod
    def get_int(cls, key, default):
        """Sozlamani int'ga o'tkazadi; parse xato bo'lsa default qaytaradi."""
        try:
            return int(cls.get(key, default))
        except (TypeError, ValueError):
            return default

    @classmethod
    def get_decimal(cls, key, default):
        """Sozlamani Decimal'ga o'tkazadi; parse xato bo'lsa Decimal(default)."""
        from decimal import InvalidOperation

        try:
            return Decimal(str(cls.get(key, default)))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(str(default))

    @classmethod
    def set(cls, key, value, description=""):
        obj, _ = cls.objects.update_or_create(
            key=key,
            defaults={"value": value, "description": description},
        )
        return obj


# --- Pro obuna ---
