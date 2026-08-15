from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class WalletPrimaryCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    card_type = serializers.CharField()
    card_last4 = serializers.CharField()
    card_holder = serializers.CharField()
    expiry = serializers.CharField()
class WalletMonthStatsSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    delta_percent = serializers.FloatField(
        allow_null=True, help_text="(bu_oy - o'tgan_oy)/o'tgan_oy*100; o'tgan oy 0 bo'lsa null"
    )
    delta_direction = serializers.ChoiceField(choices=["up", "down", "flat"])
class WalletWithdrawnStatsSerializer(serializers.Serializer):
    total = serializers.DecimalField(max_digits=14, decimal_places=2)
    last_at = serializers.DateTimeField(allow_null=True)
class WalletSummarySerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    held_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Hold davrida muzlatilgan summa",
    )
    available_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Payout uchun ochiq summa = balance - held_amount",
    )
    primary_card = WalletPrimaryCardSerializer(allow_null=True)
    cards_count = serializers.IntegerField()
    this_month = WalletMonthStatsSerializer()
    withdrawn = WalletWithdrawnStatsSerializer()
    min_payout = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Minimal pul yechish summasi (SystemSetting min_payout_amount)",
    )
class WalletOperationSerializer(serializers.Serializer):
    """Birlashtirilgan kirim/chiqim feed elementi.

    kind: income (online tarif sotuvi, +), topup (balans to'ldirish, +),
    commission (offline naqd komissiyasi, -), payout (pul yechish, -).
    """

    kind = serializers.ChoiceField(choices=["income", "payout", "topup", "commission"])
    id = serializers.IntegerField()
    amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Signed: kirim +, chiqim -",
    )
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    detail_status = serializers.CharField(
        allow_null=True,
        help_text="Faqat payout uchun: submitted|in_review|paid|rejected|cancelled",
    )
    detail_status_label = serializers.CharField(allow_blank=True)
