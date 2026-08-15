from .common import *  # noqa: F401,F403
from .user import User


class AccountDeletionRequest(models.Model):
    """Akkauntni o'chirish so'rovi (Google Play talabi).

    Foydalanuvchi mediik.uz/delete form orqali yuboradi (autentifikatsiyasiz).
    Admin telegram xabari oladi, 30 kun ichida qo'lda ko'rib chiqadi.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        PROCESSED = "processed", "O'chirildi"
        REJECTED = "rejected", "Rad etildi"

    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True, null=True)
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    admin_notes = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_deletion_requests",
    )

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "-requested_at"]),
        ]

    def __str__(self):
        return f"{self.phone} — {self.get_status_display()}"
