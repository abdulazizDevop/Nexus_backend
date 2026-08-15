from rest_framework import serializers

from .models import FamilyLink


class FamilyMemberSerializer(serializers.ModelSerializer):
    """Bemor tomonidan ko'rinadigan qator — a'zo ma'lumotlari bilan."""

    member_name = serializers.CharField(source="member.full_name", read_only=True)
    member_phone = serializers.CharField(source="member.phone", read_only=True)
    relation_display = serializers.CharField(source="get_relation_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = FamilyLink
        fields = [
            "id", "member", "member_name", "member_phone",
            "relation", "relation_display",
            "status", "status_display", "responded_at", "created_at",
        ]
        read_only_fields = fields


class FamilyInvitationSerializer(serializers.ModelSerializer):
    """A'zo tomonidan ko'rinadigan qator — bemor ma'lumotlari bilan."""

    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)
    patient_profile_id = serializers.IntegerField(read_only=True)
    relation_display = serializers.CharField(source="get_relation_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = FamilyLink
        fields = [
            "id", "patient", "patient_profile_id", "patient_name", "patient_phone",
            "relation", "relation_display",
            "status", "status_display", "responded_at", "created_at",
        ]
        read_only_fields = fields


class FamilyInviteInputSerializer(serializers.Serializer):
    """POST /family/invite/ body."""

    phone = serializers.CharField(max_length=20)
    relation = serializers.ChoiceField(
        choices=FamilyLink.Relation.choices, default=FamilyLink.Relation.BOSHQA
    )
