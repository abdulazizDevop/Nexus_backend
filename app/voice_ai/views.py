import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .prompts import LANGUAGES, personas_public
from .serializers import LiveTokenRequestSerializer

logger = logging.getLogger("mediik.voice_ai")


@extend_schema(tags=["Voice AI"])
class VoicePersonasView(APIView):
    """Ovozli hamroh — mavjud personalar + tillar (UI uchun)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        summary="Persona va til ro'yxati",
        description="Frontend persona tanlagichi uchun (system-instruction'siz).",
    )
    def get(self, request):
        return Response({"personas": personas_public(), "languages": LANGUAGES})


@extend_schema(tags=["Voice AI"])
class VoiceLiveTokenView(APIView):
    """Gemini Live sessiyasi uchun qisqa muddatli kredential.

    Client (mobil) shu kredential bilan to'g'ridan-to'g'ri Google Live API'ga
    ulanadi — audio bizning serverdan o'tmaydi. Rejim `VOICE_USE_VERTEX` bilan:
      • Vertex    → OAuth access_token + config (mobil config'ni setup'da yuboradi)
      • AI Studio → ephemeral token (config token ichiga baked)
    Persona/ovoz/til/bemor-konteksti system-instruction'ga yig'iladi.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LiveTokenRequestSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Live ovoz sessiyasi uchun kredential",
        description=(
            "Body: {\"persona\": \"quvnoq|gamgin|hazilkash|qopol\", \"lang\": \"uz|ru\"}. "
            "Javob `mode` maydoniga qarab farq qiladi:\n"
            "• vertex → {mode, access_token, expires_at, endpoint, project, location, "
            "model, model_path, voice, persona, lang, config}\n"
            "• ai_studio → {mode, token, model, voice, persona, lang}\n"
            "Har sessiya uchun yangi kredential oling; persona/til almashtirilsa — qayta so'rang."
        ),
    )
    def post(self, request):
        ser = LiveTokenRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = services.create_live_session(
                request.user,
                ser.validated_data["persona"],
                ser.validated_data["lang"],
            )
        except Exception as exc:  # noqa: BLE001 — tashqi API xatosini yumshoq qaytaramiz
            logger.error("Voice live session failed: %s", exc)
            return Response(
                {"detail": "Ovoz sessiyasini boshlab bo'lmadi. Keyinroq urinib ko'ring."},
                status=502,
            )
        return Response(result)
