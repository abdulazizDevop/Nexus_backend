"""Retsept qog'ozi skan oqimi (patient):

1) POST prescription/upload-url/  → presigned PUT URL
2) PUT  {upload_url}              → rasm S3'ga yuklanadi (client)
3) POST prescription/analyze/     → Gemini vision o'qiydi, scan pending_review
4) POST prescription/{id}/confirm/ → bemor tasdiqlagan itemlar Treatment bo'ladi
   yoki POST prescription/{id}/discard/ → rad etiladi
"""

import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPatient
from services.storage import (
    download_file_bytes,
    ext_for_mime,
    generate_upload_url,
    head_object_or_none,
)

from ..models import PrescriptionScan, Treatment
from ..models.treatment import _parse_time_str
from ..prescription_ai import analyze_prescription_image
from ..serializers import TreatmentSerializer
from ..serializers.prescription import (
    PrescriptionAnalyzeSerializer,
    PrescriptionConfirmSerializer,
    PrescriptionScanSerializer,
    PrescriptionUploadUrlSerializer,
)

logger = logging.getLogger("mediik.treatment")

PRESCRIPTION_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


@extend_schema(tags=["Treatment - Retsept skan (AI)"])
class PrescriptionUploadUrlView(APIView):
    """Retsept rasmini DO Spaces'ga yuklash uchun presigned URL."""

    permission_classes = [IsPatient]

    @extend_schema(
        request=PrescriptionUploadUrlSerializer,
        summary="Retsept rasmi uchun upload URL olish",
    )
    def post(self, request):
        ser = PrescriptionUploadUrlSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        file_type = ser.validated_data["file_type"]
        ext = ext_for_mime(file_type, fallback="jpg")
        image_key = f"prescriptions/{request.user.id}/{uuid.uuid4().hex[:8]}.{ext}"
        return Response(
            {
                "upload_url": generate_upload_url(image_key, file_type),
                "image_key": image_key,
                "expires_in": 900,
            }
        )


@extend_schema(tags=["Treatment - Retsept skan (AI)"])
class PrescriptionScanViewSet(viewsets.GenericViewSet):
    """Skanlar ro'yxati + analyze/confirm/discard oqimi."""

    permission_classes = [IsPatient]
    serializer_class = PrescriptionScanSerializer
    queryset = PrescriptionScan.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PrescriptionScan.objects.none()
        return PrescriptionScan.objects.filter(user=self.request.user)

    @extend_schema(summary="Mening skanlarim (oxirgi 20)")
    def list(self, request):
        rows = self.get_queryset()[:20]
        return Response(PrescriptionScanSerializer(rows, many=True).data)

    @extend_schema(summary="Bitta skan (tasdiqlash ekrani uchun)")
    def retrieve(self, request, pk=None):
        scan = self.get_queryset().filter(pk=pk).first()
        if not scan:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(PrescriptionScanSerializer(scan).data)

    @extend_schema(
        request=PrescriptionAnalyzeSerializer,
        summary="Retsept rasmini AI bilan o'qish (tasdiqlash uchun takliflar)",
    )
    @action(detail=False, methods=["post"])
    def analyze(self, request):
        ser = PrescriptionAnalyzeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        image_key = ser.validated_data["image_key"]

        # XAVFSIZLIK (IDOR): faqat o'z prefiksidagi rasm.
        if not image_key.startswith(f"prescriptions/{request.user.id}/"):
            return Response(
                {"detail": "Noto'g'ri image_key."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Hajm — S3 HEAD orqali oldindan (katta faylni yuklab o'tirmaymiz).
        head = head_object_or_none(image_key)
        if head is None:
            return Response(
                {"detail": "Rasm topilmadi yoki yuklab bo'lmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head["size"] > PRESCRIPTION_MAX_IMAGE_BYTES:
            return Response(
                {"detail": "Rasm hajmi 10 MB dan oshmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            image_bytes, image_mime = download_file_bytes(image_key)
        except Exception as e:
            logger.error("Retsept rasmini S3'dan olib bo'lmadi: %s", e)
            return Response(
                {"detail": "Rasm topilmadi yoki yuklab bo'lmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed = analyze_prescription_image(image_bytes, image_mime)
        if "error" in parsed:
            return Response(
                {"detail": parsed["error"]}, status=status.HTTP_502_BAD_GATEWAY
            )
        if not parsed.get("is_prescription") or not parsed.get("items"):
            return Response(
                {
                    "detail": (
                        "Rasmda retsept/tashxis qog'ozi aniqlanmadi yoki "
                        "o'qib bo'ladigan muolaja topilmadi."
                    ),
                    "warnings": parsed.get("warnings", []),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        scan = PrescriptionScan.objects.create(
            user=request.user,
            image_key=image_key,
            summary=parsed.get("summary", ""),
            ai_items=parsed["items"],
            ai_warnings=parsed.get("warnings", []),
            tokens_input=parsed.get("tokens_input", 0),
            tokens_output=parsed.get("tokens_output", 0),
        )
        return Response(
            PrescriptionScanSerializer(scan).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=PrescriptionConfirmSerializer,
        summary="Takliflarni tasdiqlash — muolajalarga qo'shiladi",
        description=(
            "Bemor AI takliflarini ko'rib (kerak bo'lsa tahrirlab) yuboradi. "
            "Har bir item Treatment bo'lib yaratiladi (self-added, created_by=null)."
        ),
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        scan = self.get_queryset().filter(pk=pk).first()
        if not scan:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if scan.status != PrescriptionScan.Status.PENDING_REVIEW:
            return Response(
                {"detail": "Bu skan allaqachon ko'rib chiqilgan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = PrescriptionConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        items = ser.validated_data["items"]

        created = []
        with transaction.atomic():
            for item in items:
                times = [t[:5] for t in item.get("times") or []]
                end_date = None
                if item.get("duration_days"):
                    end_date = timezone.localdate() + timedelta(
                        days=item["duration_days"]
                    )
                treatment = Treatment.objects.create(
                    user=request.user,
                    created_by=None,  # retsept asosida bemor o'zi qo'shdi
                    type=item["type"],
                    title=item["title"],
                    dosage=item.get("dosage") or "",
                    time=_parse_time_str(times[0]) if times else None,
                    times=times,
                    repeat=item["repeat"],
                    end_date=end_date,
                    notes=item.get("notes") or "",
                )
                created.append(treatment)

            scan.status = PrescriptionScan.Status.CONFIRMED
            scan.created_treatment_ids = [t.id for t in created]
            scan.reviewed_at = timezone.now()
            scan.save(update_fields=["status", "created_treatment_ids", "reviewed_at"])

        return Response(
            {
                "scan": PrescriptionScanSerializer(scan).data,
                "created_treatments": TreatmentSerializer(
                    created, many=True, context={"request": request}
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Takliflarni rad etish (hech narsa qo'shilmaydi)")
    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        scan = self.get_queryset().filter(pk=pk).first()
        if not scan:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if scan.status != PrescriptionScan.Status.PENDING_REVIEW:
            return Response(
                {"detail": "Bu skan allaqachon ko'rib chiqilgan."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        scan.status = PrescriptionScan.Status.DISCARDED
        scan.reviewed_at = timezone.now()
        scan.save(update_fields=["status", "reviewed_at"])
        return Response(PrescriptionScanSerializer(scan).data)
