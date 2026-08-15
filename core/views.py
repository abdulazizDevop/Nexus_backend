"""Umumiy / cross-cutting view'lar.

Hozir bu yerda faqat tarjima endpoint'i bor (admin uchun "Auto-tarjima"
tugmasi orqali chaqiriladi).
"""

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample

from core.i18n import SUPPORTED_LANGS
from core.permissions import IsSuperOrSimpleAdmin
from services.translate import auto_translate_all, translate_one


class TranslateRequestSerializer(serializers.Serializer):
    text = serializers.CharField()
    source = serializers.ChoiceField(choices=SUPPORTED_LANGS)
    # Ixtiyoriy — agar berilsa, faqat shu tilga tarjima qilinadi.
    # Berilmasa — 3 tilga ham qaytariladi.
    target = serializers.ChoiceField(
        choices=SUPPORTED_LANGS, required=False, allow_null=True
    )


@extend_schema(
    tags=["i18n"],
    summary="Matnni 3 tilga avtomatik tarjima qilish (admin)",
    description=(
        "Admin paneldagi 'Auto-tarjima' tugmasi shu endpoint'ni chaqiradi.\n\n"
        "- Manba til as-is qoldiriladi.\n"
        "- O'zbek Lotin ↔ Kirill: transliteratsiya (oflayn, deterministik).\n"
        "- O'zbek ↔ Rus: Gemini AI (Redis cache 24 soat).\n\n"
        "**Iqtisodiy ravishda:**\n"
        "- Bir xil matn 24 soat ichida qayta tarjima qilinmaydi (cache hit).\n"
        "- Faqat admin yangi yozuv kiritganda yoki tahrir qilganda chaqiriladi.\n"
        "- Mobile/admin ro'yxat o'qiyotganda **chaqirilmaydi** — saqlangan "
        "JSON'dan o'qiladi."
    ),
    request=TranslateRequestSerializer,
    examples=[
        OpenApiExample(
            "Uzbek → 3 til",
            value={"text": "Kardiolog", "source": "uz"},
            request_only=True,
        ),
        OpenApiExample(
            "Faqat ruschaga",
            value={"text": "Yurak shifokori", "source": "uz", "target": "ru"},
            request_only=True,
        ),
        OpenApiExample(
            "3 til response",
            value={"uz": "Kardiolog", "ru": "Кардиолог", "cyr": "Кардиолог"},
            response_only=True,
        ),
    ],
)
@api_view(["POST"])
@permission_classes([IsSuperOrSimpleAdmin])
def translate_view(request):
    serializer = TranslateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    text = serializer.validated_data["text"].strip()
    source = serializer.validated_data["source"]
    target = serializer.validated_data.get("target")

    if not text:
        return Response(
            {"detail": "text bo'sh bo'lmasligi kerak."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if target:
        translated = translate_one(text, source, target)
        return Response({target: translated})

    return Response(auto_translate_all(text, source))
