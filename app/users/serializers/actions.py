from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + konstantalar


class DeleteMyAccountSerializer(serializers.Serializer):
    """O'z akkauntini yoki profilini o'chirish so'rovi (autentifikatsiyalangan user)."""

    scope = serializers.ChoiceField(
        choices=["all", "doctor", "patient"],
        default="all",
        required=False,
        help_text=(
            "Nimani o'chirish:\n"
            "- `all` (default): butun akkaunt (ikkala profil) — legacy.\n"
            "- `doctor`: faqat doctor profili — User bemor sifatida qoladi.\n"
            "- `patient`: faqat bemor datasi — doctor profili bo'lsa User doctor "
            "sifatida qoladi, bo'lmasa butun akkaunt o'chadi."
        ),
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Ixtiyoriy: nima sababdan o'chirayotganligi (audit uchun)",
    )
    refresh = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Joriy refresh token — yuborilsa darhol blacklist'ga qo'shiladi. "
            "Yuborilmasa ham user'ning barcha outstanding tokenlari blacklist qilinadi."
        ),
    )


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=User.Role.choices)
    admin_type = serializers.ChoiceField(
        choices=User.AdminType.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate(self, data):
        if data["role"] == User.Role.ADMIN and not data.get("admin_type"):
            raise serializers.ValidationError(
                {"admin_type": "Admin uchun admin_type majburiy."}
            )
        if data["role"] != User.Role.ADMIN:
            data["admin_type"] = None
        return data
