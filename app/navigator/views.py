"""AI Navigator API (ai_navigator_api_contract.md bo'yicha).

Xatolik formati (kontrakt §10): {"detail": machine_code, "message": matn}.
"""

import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from app.medical.models import MedicalCondition, RoadmapStep
from core.i18n import get_request_lang
from core.permissions import IsPatient

from . import ai, services
from .models import NavConversation, NavMessage
from .serializers import (
    ChatRequestSerializer,
    DiagnosisCreateSerializer,
    DiagnosisDetailSerializer,
    DiagnosisListSerializer,
    TriageRequestSerializer,
)

logger = logging.getLogger("mediik.navigator")

FROM_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB (kontrakt §4)
CHAT_DAILY_LIMIT = 30  # kuniga savol (kontrakt §10: daily_limit_exceeded)


def _err(code: str, message: str, http_status: int) -> Response:
    return Response({"detail": code, "message": message}, status=http_status)


def _ai_unavailable() -> Response:
    return _err(
        "ai_unavailable", "AI hozir band, keyinroq urinib ko'ring.",
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@extend_schema(tags=["Navigator"])
class NavigatorDiagnosisViewSet(viewsets.GenericViewSet):
    """Tashxislar: ro'yxat, bittasi, qo'lda kiritish, rasmdan (kontrakt §1-§5)."""

    permission_classes = [IsPatient]
    serializer_class = DiagnosisListSerializer
    queryset = MedicalCondition.objects.none()
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MedicalCondition.objects.none()
        # Navigator faqat roadmap'li tashxislar bilan ishlaydi
        return (
            MedicalCondition.objects.filter(user=self.request.user)
            .exclude(roadmap_steps__isnull=True)
            .distinct()
            .select_related("doctor_profile__user", "doctor_profile__specialty")
            .order_by("-is_active", "-created_at")
        )

    @extend_schema(summary="Tashxislar ro'yxati (kontrakt §1)")
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        ser = DiagnosisListSerializer(page, many=True)
        return self.get_paginated_response(ser.data)

    @extend_schema(summary="Tashxis + to'liq roadmap (kontrakt §2)")
    def retrieve(self, request, pk=None):
        obj = self.get_queryset().filter(pk=pk).first()
        if not obj:
            return _err("not_found", "Tashxis topilmadi.", status.HTTP_404_NOT_FOUND)
        return Response(DiagnosisDetailSerializer(obj).data)

    @extend_schema(
        request=DiagnosisCreateSerializer,
        summary="Qo'lda tashxis kiritish → AI roadmap quradi (kontrakt §5)",
    )
    def create(self, request):
        ser = DiagnosisCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        lang = get_request_lang(request)

        parsed = ai.generate_roadmap(d["title"], d.get("icd10") or "", lang)
        if not parsed:
            return _ai_unavailable()

        with transaction.atomic():
            MedicalCondition.objects.filter(
                user=request.user, is_active=True
            ).update(is_active=False)
            condition = MedicalCondition.objects.create(
                user=request.user,
                added_by=request.user,
                type=MedicalCondition.Type.CHRONIC,
                name=d["title"],
                icd10=(d.get("icd10") or "")[:10],
                source=MedicalCondition.DiagnosisSource.MANUAL,
                is_active=True,
                discovered_at=d.get("diagnosed_at") or timezone.localdate(),
            )
            services.apply_ai_fields(condition, parsed)
            services.materialize_roadmap(condition, parsed)

        return Response(
            DiagnosisDetailSerializer(condition).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(summary="Tashxis qog'ozi rasmidan (kontrakt §4)")
    @action(detail=False, methods=["post"], url_path="from-image")
    def from_image(self, request):
        image = request.FILES.get("image")
        if not image:
            return _err(
                "image_required", "image fayli majburiy.", status.HTTP_400_BAD_REQUEST
            )
        if image.size > FROM_IMAGE_MAX_BYTES:
            return _err(
                "image_too_large", "Rasm hajmi 10 MB dan oshmasligi kerak.",
                status.HTTP_400_BAD_REQUEST,
            )
        note = (request.data.get("note") or "").strip()
        lang = get_request_lang(request)

        # §11: rasm SAQLANMAYDI — xotirada o'qiladi, faqat matn qoladi.
        image_bytes = image.read()
        parsed = ai.extract_and_build_from_image(
            image_bytes, image.content_type or "image/jpeg", lang, note
        )
        if parsed is None:
            return _ai_unavailable()
        if not parsed.get("is_medical_document") or not (
            parsed.get("diagnosis_title") or ""
        ).strip():
            return _err(
                "document_unreadable", "Hujjatni o'qib bo'lmadi.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        confidence = round(float(parsed.get("confidence") or 0), 2)
        needs_review = bool(parsed.get("needs_review")) or confidence < 0.6

        with transaction.atomic():
            MedicalCondition.objects.filter(
                user=request.user, is_active=True
            ).update(is_active=False)
            condition = MedicalCondition.objects.create(
                user=request.user,
                added_by=request.user,
                type=MedicalCondition.Type.CHRONIC,
                name=parsed["diagnosis_title"][:200],
                icd10=(parsed.get("icd10") or "")[:10],
                source=MedicalCondition.DiagnosisSource.DOCUMENT,
                is_active=True,
                discovered_at=timezone.localdate(),
                extraction={
                    "confidence": confidence,
                    "recognized_text": parsed.get("recognized_text") or "",
                    "needs_review": needs_review,
                },
            )
            services.apply_ai_fields(condition, parsed)
            services.materialize_roadmap(condition, parsed)

        data = DiagnosisDetailSerializer(condition).data
        data["extraction"] = condition.extraction
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Navigator"])
class ActiveRoadmapView(APIView):
    """Home ekrani — joriy aktiv roadmap (kontrakt §3)."""

    permission_classes = [IsPatient]

    @extend_schema(summary="Aktiv roadmap (yo'q bo'lsa {\"diagnosis\": null})")
    def get(self, request):
        condition = (
            MedicalCondition.objects.filter(user=request.user, is_active=True)
            .order_by("-created_at")
            .first()
        )
        if not condition:
            return Response({"diagnosis": None})
        return Response(DiagnosisDetailSerializer(condition).data)


@extend_schema(tags=["Navigator"])
class StepCompleteView(APIView):
    """Qadamni bajarish — keyingi locked ochiladi (kontrakt §6)."""

    permission_classes = [IsPatient]

    @extend_schema(summary="Qadamni bajarilgan deb belgilash")
    def post(self, request, pk: int):
        step = RoadmapStep.objects.filter(pk=pk, user=request.user).first()
        if not step:
            return _err("not_found", "Qadam topilmadi.", status.HTTP_404_NOT_FOUND)
        unlocked = services.complete_step(step)
        return Response(
            {
                "step": {
                    "id": step.id,
                    "status": step.status,
                    "completed_at": step.completed_at,
                },
                "roadmap_progress": services.roadmap_progress(step.condition),
                "unlocked_step_ids": unlocked,
            }
        )


@extend_schema(tags=["Navigator"])
class TriageView(APIView):
    """Simptom → mutaxassis (kontrakt §7)."""

    permission_classes = [IsPatient]

    @extend_schema(request=TriageRequestSerializer, summary="Triaj")
    def post(self, request):
        ser = TriageRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        lang = get_request_lang(request)

        diagnosis = None
        if ser.validated_data.get("diagnosis_id"):
            diagnosis = MedicalCondition.objects.filter(
                pk=ser.validated_data["diagnosis_id"], user=request.user
            ).first()
        context = services.build_patient_context(request.user, diagnosis)

        parsed = ai.triage(ser.validated_data["complaint"], context, lang)
        if not parsed:
            return _ai_unavailable()

        return Response(
            {
                "urgency": parsed["urgency"],
                "summary": parsed["summary"],
                "advice": parsed.get("advice") or [],
                "recommended_specialties": parsed.get("recommended_specialties") or [],
                "recommended_doctors": services.recommended_doctors_for(
                    parsed.get("recommended_specialties") or []
                ),
                "disclaimer": parsed.get("disclaimer")
                or "Bu tashxis emas. Holatingiz yomonlashsa shifokorga murojaat qiling.",
            }
        )


@extend_schema(tags=["Navigator"])
class NavigatorChatView(APIView):
    """Kontekstli AI chat (kontrakt §8) — kontekstni backend yig'adi."""

    permission_classes = [IsPatient]

    @extend_schema(request=ChatRequestSerializer, summary="Navigator AI chat")
    def post(self, request):
        ser = ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        lang = get_request_lang(request)

        # Kunlik limit (kontrakt §10: daily_limit_exceeded)
        limit_key = f"navchat:{request.user.id}:{timezone.localdate().isoformat()}"
        used = cache.get(limit_key, 0)
        if used >= CHAT_DAILY_LIMIT:
            return _err(
                "daily_limit_exceeded", "Bugungi savollar limiti tugadi.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Suhbat: "c-{id}" yoki yangi
        conversation = None
        raw_cid = (d.get("conversation_id") or "").strip()
        if raw_cid:
            try:
                cid = int(raw_cid.removeprefix("c-"))
            except ValueError:
                cid = None
            if cid:
                conversation = NavConversation.objects.filter(
                    pk=cid, user=request.user
                ).first()

        diagnosis = None
        if d.get("diagnosis_id"):
            diagnosis = MedicalCondition.objects.filter(
                pk=d["diagnosis_id"], user=request.user
            ).first()
        if diagnosis is None:
            diagnosis = MedicalCondition.objects.filter(
                user=request.user, is_active=True
            ).first()

        if conversation is None:
            conversation = NavConversation.objects.create(
                user=request.user, diagnosis=diagnosis
            )

        history = [
            {"role": "model" if m.role == NavMessage.Role.ASSISTANT else "user",
             "text": m.content}
            for m in conversation.messages.order_by("-created_at")[:10][::-1]
        ]
        context = services.build_patient_context(request.user, diagnosis)

        parsed = ai.chat_reply(d["message"], context, history, lang)
        if not parsed:
            return _ai_unavailable()

        with transaction.atomic():
            NavMessage.objects.create(
                conversation=conversation,
                role=NavMessage.Role.USER,
                content=d["message"],
            )
            NavMessage.objects.create(
                conversation=conversation,
                role=NavMessage.Role.ASSISTANT,
                content=parsed["reply"],
                tokens_input=parsed.get("tokens_input", 0),
                tokens_output=parsed.get("tokens_output", 0),
            )
            conversation.save(update_fields=["updated_at"])
        cache.set(limit_key, used + 1, 60 * 60 * 24)

        # Faqat bemorning o'z qadam id'lari qaytsin (AI xatosidan himoya)
        own_ids = set(
            RoadmapStep.objects.filter(user=request.user).values_list("id", flat=True)
        )
        related = [i for i in (parsed.get("related_step_ids") or []) if i in own_ids]

        return Response(
            {
                "conversation_id": conversation.public_id,
                "reply": parsed["reply"],
                "recommended_doctors": [],
                "related_step_ids": related,
                "disclaimer": (parsed.get("disclaimer") or None)
                if parsed.get("needs_doctor") or parsed.get("disclaimer")
                else None,
            }
        )
