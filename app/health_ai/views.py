"""Health AI endpointlari — FAQAT doctor.

  - AIHealthReportViewSet  — kunlik AI insight hisobotlari (read + seen + generate + today)
  - AiConversationViewSet  — doctor↔AI chat (list/create + messages GET/POST)

Bemor bu endpointlarga kira olmaydi (IsDoctor + DoctorPatient ACCEPTED tekshiruvi).
"""

import json
import logging

from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from services.gemini import generate_text, generate_text_stream, generate_with_audio

from app.doctors.models import DoctorPatient
from core.i18n import get_request_lang
from core.permissions import IsDoctor, IsVerifiedDoctor

from . import prompts, services
from .models import AIHealthReport, AiConversation, AiMessage
from .serializers import (
    AIHealthReportSerializer,
    AiConversationSerializer,
    AiMessageSerializer,
)
from .tasks import generate_one_report

logger = logging.getLogger(__name__)

# Severity sort — critical tepada (skrinshotdagidek).
_SEVERITY_RANK = {"critical": 0, "attention": 1, "normal": 2}


def _doctor_access(user, patient_id):
    """(profile, ok) — doctor shu bemorga ACCEPTED bog'langanmi (diet pattern)."""
    profile = getattr(user, "doctor_profile", None)
    if not profile:
        return None, False
    link = (
        DoctorPatient.objects.filter(
            doctor=profile, patient_id=patient_id, status=DoctorPatient.Status.ACCEPTED
        )
        .values("patient_profile_id")
        .first()
    )
    return profile, link  # link None bo'lsa ruxsat yo'q; aks holда {patient_profile_id}


@extend_schema(tags=["Health AI - Report"])
class AIHealthReportViewSet(viewsets.ReadOnlyModelViewSet):
    """Kunlik AI insight hisobotlari — doctor o'z bemorlariniki."""

    queryset = AIHealthReport.objects.none()
    serializer_class = AIHealthReportSerializer
    permission_classes = [IsVerifiedDoctor]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIHealthReport.objects.none()
        profile = getattr(self.request.user, "doctor_profile", None)
        if not profile:
            return AIHealthReport.objects.none()
        qs = AIHealthReport.objects.filter(doctor=profile).select_related("patient")
        patient_id = self.request.query_params.get("patient_id")
        if patient_id and str(patient_id).isdigit():
            qs = qs.filter(patient_id=patient_id)
        return qs

    @extend_schema(summary="Bugungi AI insightlar (critical tepada)")
    @action(detail=False, methods=["get"])
    def today(self, request):
        rows = list(self.get_queryset().filter(period_start=timezone.localdate()))
        rows.sort(key=lambda r: (_SEVERITY_RANK.get(r.severity, 9), -r.id))
        return Response(self.get_serializer(rows, many=True).data)

    @extend_schema(summary="Hisobotni o'qilgan deb belgilash")
    @action(detail=True, methods=["post"])
    def seen(self, request, pk=None):
        report = self.get_object()
        if report.seen_at is None:
            report.seen_at = timezone.now()
            report.save(update_fields=["seen_at"])
        return Response(self.get_serializer(report).data)

    @extend_schema(summary="On-demand generatsiya (bemor uchun hozir)")
    @action(detail=False, methods=["post"])
    def generate(self, request):
        patient_id = request.data.get("patient_id")
        if not patient_id or not str(patient_id).isdigit():
            return Response({"detail": "patient_id kerak"}, status=400)
        profile, link = _doctor_access(request.user, patient_id)
        if not link:
            return Response({"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404)
        if not link["patient_profile_id"]:
            return Response({"detail": "Bemor profili topilmadi."}, status=404)

        today = timezone.localdate()
        # Sinxron (doctor kutadi). bind=True task — .apply() eager ishlatadi.
        generate_one_report.apply(
            kwargs={
                "doctor_id": profile.id,
                "patient_id": int(patient_id),
                "patient_profile_id": link["patient_profile_id"],
                "period_date": today.isoformat(),
                "force": True,  # doctor ataylab so'radi — activity-filter/idempotency bypass
                "language": get_request_lang(request),
            }
        )
        report = AIHealthReport.objects.filter(
            doctor=profile, patient_id=patient_id, period_start=today
        ).first()
        if not report:
            return Response(
                {"detail": "Ma'lumot yetarli emas yoki AI javob bermadi."}, status=422
            )
        return Response(self.get_serializer(report).data)


@extend_schema(tags=["Health AI - Doctor Chat"])
class AiConversationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Doctor↔AI chat — doctor bemor bo'yicha savol beradi."""

    queryset = AiConversation.objects.none()
    serializer_class = AiConversationSerializer
    permission_classes = [IsVerifiedDoctor]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AiConversation.objects.none()
        profile = getattr(self.request.user, "doctor_profile", None)
        if not profile:
            return AiConversation.objects.none()
        qs = AiConversation.objects.filter(doctor_profile=profile).select_related("patient")
        patient_id = self.request.query_params.get("patient_id")
        if patient_id and str(patient_id).isdigit():
            qs = qs.filter(patient_id=patient_id)
        return qs

    def create(self, request, *args, **kwargs):
        patient_id = request.data.get("patient_id")
        if not patient_id or not str(patient_id).isdigit():
            return Response({"detail": "patient_id kerak"}, status=400)
        profile, link = _doctor_access(request.user, patient_id)
        if not link:
            return Response({"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404)
        lang = getattr(getattr(request.user, "settings", None), "language", None) or "uz"
        convo = AiConversation.objects.create(
            doctor_profile=profile,
            patient_id=int(patient_id),
            patient_profile_id=link["patient_profile_id"],
            language=lang,
        )
        return Response(self.get_serializer(convo).data, status=201)

    @extend_schema(summary="Suhbat xabarlari (GET) / savol yuborish (POST)")
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        convo = self.get_object()  # get_queryset doctor egaligini ta'minlaydi
        if request.method == "GET":
            return Response(
                AiMessageSerializer(convo.messages.all(), many=True).data
            )

        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"detail": "Bo'sh xabar"}, status=400)

        patient = convo.patient
        context = (
            services.build_patient_context(patient) if patient else "(bemor ma'lumoti yo'q)"
        )
        trend = services.build_indicator_trend(patient, months=3) if patient else ""
        system_prompt = prompts.build_chat_system_prompt(convo.language, context, trend)
        history = services.build_history_for_ai(convo)

        result = generate_text(
            prompt=content,
            system_instruction=system_prompt,
            history=history,
            temperature=0.5,
        )
        if "error" in result:
            return Response({"detail": result["error"]}, status=503)

        with transaction.atomic():
            AiMessage.objects.create(
                conversation=convo, role=AiMessage.Role.USER, content=content
            )
            assistant = AiMessage.objects.create(
                conversation=convo,
                role=AiMessage.Role.ASSISTANT,
                content=result.get("text") or "",
                tokens_input=result.get("tokens_input", 0),
                tokens_output=result.get("tokens_output", 0),
            )
            if not convo.title:
                convo.title = services.auto_generate_title(content)
                convo.save(update_fields=["title", "updated_at"])
            else:
                convo.save(update_fields=["updated_at"])

        return Response(AiMessageSerializer(assistant).data)

    @extend_schema(summary="SSE streaming javob (live token oqimi)")
    @action(detail=True, methods=["post"], url_path="stream")
    def stream(self, request, pk=None):
        """Savol → Gemini'ni token-token SSE oqimi (text/event-stream).

        Event'lar: `data: {"delta": "..."}` har bo'lak, oxirida
        `data: {"done": true, "message_id": N}`; xato bo'lsa `data: {"error": "..."}`.
        Xabarlar (user + assistant) oqim tugagach atomik saqlanadi (xato bo'lsa saqlanmaydi).
        """
        convo = self.get_object()  # get_queryset doctor egaligini ta'minlaydi
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"detail": "Bo'sh xabar"}, status=400)

        patient = convo.patient
        context = (
            services.build_patient_context(patient) if patient else "(bemor ma'lumoti yo'q)"
        )
        trend = services.build_indicator_trend(patient, months=3) if patient else ""
        system_prompt = prompts.build_chat_system_prompt(convo.language, context, trend)
        history = services.build_history_for_ai(convo)

        def event_stream():
            # Darhol birinchi bayt — nginx/proxy ulanishni ochib, buffering yoki
            # read-timeout ishga tushmasligi uchun (X-Accel-Buffering: no bilan birga).
            yield ": connected\n\n"

            # Savolni darhol saqlaymiz — stream uzilsa yoki AI xato bersa ham
            # shifokorning savoli yo'qolmaydi.
            AiMessage.objects.create(
                conversation=convo, role=AiMessage.Role.USER, content=content
            )

            parts = []
            usage = {"tokens_input": 0, "tokens_output": 0}
            errored = False
            try:
                for ev in generate_text_stream(
                    prompt=content,
                    system_instruction=system_prompt,
                    history=history,
                    temperature=0.5,
                ):
                    if "delta" in ev:
                        parts.append(ev["delta"])
                        yield f"data: {json.dumps({'delta': ev['delta']})}\n\n"
                    elif "error" in ev:
                        errored = True
                        yield f"data: {json.dumps({'error': ev['error']})}\n\n"
                        break
                    elif ev.get("done"):
                        usage["tokens_input"] = ev.get("tokens_input", 0)
                        usage["tokens_output"] = ev.get("tokens_output", 0)
            except Exception:  # noqa: BLE001
                logger.exception("AI chat stream xato (convo=%s)", convo.id)
                errored = True
                yield f"data: {json.dumps({'error': 'AI javob oqimida xato yuz berdi.'})}\n\n"

            text = "".join(parts)
            if not text:
                if not errored:
                    yield f"data: {json.dumps({'error': 'AI javob qaytarmadi'})}\n\n"
                return

            # Qisman yoki to'liq javobni saqlaymiz (xato bo'lsa ham kelgan qismi).
            assistant = AiMessage.objects.create(
                conversation=convo,
                role=AiMessage.Role.ASSISTANT,
                content=text,
                tokens_input=usage["tokens_input"],
                tokens_output=usage["tokens_output"],
            )
            if not convo.title:
                convo.title = services.auto_generate_title(content)
                convo.save(update_fields=["title", "updated_at"])
            else:
                convo.save(update_fields=["updated_at"])

            yield f"data: {json.dumps({'done': True, 'message_id': assistant.id})}\n\n"

        resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"  # nginx buffering o'chirish (SSE uchun)
        return resp

    @extend_schema(summary="Ovozli savol → matn (STT, Gemini audio)")
    @action(detail=False, methods=["post"], url_path="transcribe")
    def transcribe(self, request):
        """Doctor mikrofondan gapiradi → audio yuboriladi → matn qaytadi.

        multipart/form-data: `audio` (webm/mp4/wav/ogg/mp3). Javob: {"text": "..."}.
        """
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"detail": "Audio fayl kerak (maydon: audio)"}, status=400)
        if audio.size > 10 * 1024 * 1024:  # 10MB
            return Response({"detail": "Audio juda katta (max 10MB)"}, status=400)

        lang = get_request_lang(request)
        instruction = {
            "ru": "Преобразуйте эту аудиозапись в ТЕКСТ (транскрипция). "
            "Верните ТОЛЬКО сказанное, без комментариев и пояснений.",
        }.get(
            lang,
            "Ushbu audioni MATNGA aylantiring (transkripsiya). "
            "FAQAT aytilgan matnni qaytaring, izoh yoki tushuntirishsiz.",
        )
        result = generate_with_audio(
            prompt=instruction,
            audio_bytes=audio.read(),
            audio_mime_type=getattr(audio, "content_type", None) or "audio/webm",
        )
        if "error" in result:
            return Response({"detail": result["error"]}, status=503)
        return Response({"text": (result.get("text") or "").strip()})
