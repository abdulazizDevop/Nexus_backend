from rest_framework import serializers

from app.medical.models import MedicalCondition, RoadmapStep

from .services import roadmap_progress


class RoadmapStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoadmapStep
        fields = [
            "id", "order", "type", "status", "title", "description",
            "body", "due_date", "completed_at", "payload",
        ]
        read_only_fields = fields


class _DoctorBriefMixin(serializers.Serializer):
    def get_doctor(self, obj):
        p = obj.doctor_profile
        if not p:
            return None
        return {
            "id": p.id,
            "full_name": p.user.full_name,
            "specialty": getattr(p.specialty, "name", "") or "",
        }


class DiagnosisListSerializer(_DoctorBriefMixin, serializers.ModelSerializer):
    """Kontrakt §1 — ro'yxat elementi."""

    title = serializers.CharField(source="name", read_only=True)
    diagnosed_at = serializers.DateField(source="discovered_at", read_only=True)
    doctor = serializers.SerializerMethodField()
    roadmap_progress = serializers.SerializerMethodField()

    class Meta:
        model = MedicalCondition
        fields = [
            "id", "title", "icd10", "source", "is_active",
            "diagnosed_at", "doctor", "roadmap_progress",
        ]
        read_only_fields = fields

    def get_roadmap_progress(self, obj):
        return roadmap_progress(obj)


class DiagnosisDetailSerializer(DiagnosisListSerializer):
    """Kontrakt §2 — tashxis + to'liq roadmap."""

    roadmap = serializers.SerializerMethodField()

    class Meta(DiagnosisListSerializer.Meta):
        fields = [
            "id", "title", "icd10", "source", "is_active", "diagnosed_at",
            "doctor", "plain_explanation", "what_to_watch", "red_flags",
            "roadmap",
        ]
        read_only_fields = fields

    def get_roadmap(self, obj):
        steps = RoadmapStep.objects.filter(condition=obj)
        progress = roadmap_progress(obj)
        return {
            "id": obj.id,  # alohida roadmap jadvali yo'q — condition id ishlatiladi
            **progress,
            "steps": RoadmapStepSerializer(steps, many=True).data,
        }


class DiagnosisCreateSerializer(serializers.Serializer):
    """Kontrakt §5 — qo'lda tashxis kiritish."""

    title = serializers.CharField(max_length=200)
    icd10 = serializers.CharField(
        max_length=10, required=False, allow_null=True, allow_blank=True, default=""
    )
    diagnosed_at = serializers.DateField(required=False, allow_null=True, default=None)


class TriageRequestSerializer(serializers.Serializer):
    """Kontrakt §7."""

    complaint = serializers.CharField(max_length=2000)
    diagnosis_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class ChatRequestSerializer(serializers.Serializer):
    """Kontrakt §8."""

    message = serializers.CharField(max_length=4000)
    conversation_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    diagnosis_id = serializers.IntegerField(required=False, allow_null=True, default=None)
