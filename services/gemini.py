"""Gemini API wrapper.

- GEMINI_USE_VERTEX=true → bitta Vertex AI (ADC) klient; aks holda 5 ta
  GEMINI_API_KEY o'rtasida random rotation (rate limit'dan qochish uchun)
- Text va multimodal (rasm/audio + text) generatsiya
- Streaming (WebSocket'dan ishlatish uchun)
- Xato holida keyingi klient bilan retry
"""

import hashlib
import logging
import random
from typing import Any

from django.conf import settings
from google import genai
from google.genai import types

from services.storage import AUDIO_MIMES

logger = logging.getLogger(__name__)


# --- Helpers ---


def _get_api_keys() -> list[str]:
    """.env dan barcha GEMINI_API_KEY_1..5 ni o'qib, bo'sh bo'lmaganlarini qaytaradi."""
    keys = []
    for i in range(1, 6):
        key = getattr(settings, f"GEMINI_API_KEY_{i}", None)
        if key:
            keys.append(key)
    # Fallback: eski single key
    fallback = getattr(settings, "GEMINI_API_KEY", None)
    if fallback and fallback not in keys:
        keys.append(fallback)
    return keys


_clients: dict[str, genai.Client] = {}


def _get_client(api_key: str) -> genai.Client:
    """Per-key Gemini klient cache — har key uchun bitta klient."""
    client = _clients.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key)
        _clients[api_key] = client
    return client


def _use_vertex() -> bool:
    """Vertex AI rejimi yoqilganmi (GEMINI_USE_VERTEX=true)."""
    return bool(getattr(settings, "GEMINI_USE_VERTEX", False))


_vertex_client: genai.Client | None = None


def _get_vertex_client() -> genai.Client:
    """Vertex AI klient (ADC auth) — bitta cache. $300/postpay, prepay devori yo'q.

    api_key ISHLATMAYDI — Application Default Credentials (service account / gcloud)
    orqali autentifikatsiya. Voice AI'ga tegishi yo'q (u alohida oqim).
    """
    global _vertex_client
    if _vertex_client is None:
        _vertex_client = genai.Client(
            vertexai=True,
            project=getattr(settings, "GOOGLE_CLOUD_PROJECT", None) or None,
            location=getattr(settings, "GEMINI_VERTEX_LOCATION", "us-central1"),
        )
    return _vertex_client


def _clients_to_try() -> list[tuple[str, genai.Client]]:
    """Urinib ko'riladigan (label, client) ro'yxati.

    - Vertex rejimida: bitta ADC klient (rotatsiya yo'q — ADC yagona manba).
    - Aks holda: GEMINI_API_KEY_* random rotatsiyasi (rate-limit'dan qochish).
    """
    if _use_vertex():
        return [("vertex", _get_vertex_client())]
    keys = _get_api_keys()
    return [(_key_id(k), _get_client(k)) for k in random.sample(keys, k=len(keys))]


def _get_model_name() -> str:
    return getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")


def _key_id(api_key: str) -> str:
    """API kalitidan log uchun maskalangan identifikator (secret material chiqmaydi)."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:6]


def _build_config(
    system_instruction: str | None,
    temperature: float = 0.7,
    max_tokens: int | None = 8192,
    response_schema: dict | None = None,
) -> types.GenerateContentConfig:
    """GenerateContentConfig yaratadi.

    - max_tokens=None berilsa limit qo'yilmaydi (to'liq javob).
    - response_schema berilsa — kafolatlangan JSON (response_mime_type avtomatik
      "application/json" bo'ladi).
    """
    kwargs: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_output_tokens"] = max_tokens
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    if response_schema is not None:
        kwargs["response_schema"] = response_schema
        kwargs["response_mime_type"] = "application/json"
    return types.GenerateContentConfig(**kwargs)


def _build_text_contents(
    prompt: str, history: list[dict] | None
) -> list[types.Content]:
    """History + new user prompt → Gemini Content list."""
    contents: list[types.Content] = []
    if history:
        for msg in history:
            role = msg.get("role", "user")
            text = (msg.get("text") or "").strip()
            if not text or role not in ("user", "model"):
                continue
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=text)],
                )
            )
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    )
    return contents


def _build_multimodal_contents(
    prompt: str, data: bytes, mime_type: str
) -> list[types.Content]:
    """Image/audio + text → bitta user Content (multimodal)."""
    return [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
        )
    ]


def _extract_usage(response) -> tuple[int, int]:
    """Response'dan input/output token sonini xavfsiz olish."""
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return 0, 0
    tin = getattr(usage, "prompt_token_count", 0) or 0
    tout = getattr(usage, "candidates_token_count", 0) or 0
    return tin, tout


def _generate(
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    *,
    error_label: str,
    user_error: str,
) -> dict:
    """Barcha generatsiya funksiyalari uchun umumiy urinish loop'i.

    `_clients_to_try()` bergan klientlar bilan navbatma-navbat urinadi (API-key
    rejimida random rotatsiya, Vertex rejimida bitta ADC klient); birinchi
    muvaffaqiyat — qaytaradi. Hammasi muvaffaqiyatsiz bo'lsa — `user_error`.
    """
    attempts = _clients_to_try()
    if not attempts:
        return {"error": "AI xizmati sozlanmagan."}

    last_error = None
    for label, client in attempts:
        try:
            response = client.models.generate_content(
                model=_get_model_name(),
                contents=contents,
                config=config,
            )
            tin, tout = _extract_usage(response)
            return {
                "text": response.text or "",
                "tokens_input": tin,
                "tokens_output": tout,
            }
        except Exception as e:
            last_error = str(e)
            logger.warning("Gemini %s xatolik (client=%s): %s", error_label, label, e)
            continue

    logger.error("Gemini %s barcha urinishda muvaffaqiyatsiz: %s", error_label, last_error)
    return {"error": user_error}


# --- Public API ---


def generate_text(
    prompt: str,
    system_instruction: str | None = None,
    history: list[dict] | None = None,
    response_schema: dict | None = None,
    max_tokens: int | None = 8192,
    temperature: float = 0.7,
) -> dict:
    """Text-only generatsiya (ixtiyoriy structured JSON).

    Args:
        prompt: Foydalanuvchi savoli / topshiriq
        system_instruction: System prompt (context + qoidalar)
        history: Oldingi xabarlar [{"role": "user|model", "text": "..."}]
        response_schema: berilsa — kafolatlangan JSON (response_mime_type=application/json).
            Schema'da `required` MAJBURIY bo'lsin (aks holda model maydonni bo'sh qoldiradi).
        max_tokens / temperature: generatsiya sozlamalari (report uchun past temp).

    Returns:
        success: {"text": str, "tokens_input": int, "tokens_output": int}
        error:   {"error": str}
    """
    return _generate(
        _build_text_contents(prompt, history),
        _build_config(
            system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
        ),
        error_label="text",
        user_error="AI javob bera olmadi. Iltimos, qaytadan urinib ko'ring.",
    )


def generate_text_stream(
    prompt: str,
    system_instruction: str | None = None,
    history: list[dict] | None = None,
    temperature: float = 0.7,
):
    """Text streaming (SSE uchun) — chunk'larni yield qiladi.

    Yields:
        {"delta": str}                                    — har matn bo'lagi
        {"done": True, "tokens_input", "tokens_output"}   — yakun
        {"error": str}                                    — xato (terminal)

    Key-rotation faqat stream BOSHLANISHIDAN oldin — yarim javob kelganda qayta
    urinmaymiz (dublikat matn bo'lmasin).
    """
    attempts = _clients_to_try()
    if not attempts:
        yield {"error": "AI xizmati sozlanmagan."}
        return

    contents = _build_text_contents(prompt, history)
    config = _build_config(system_instruction, temperature=temperature)

    last_error = None
    for label, client in attempts:
        started = False
        tin = tout = 0
        try:
            stream = client.models.generate_content_stream(
                model=_get_model_name(),
                contents=contents,
                config=config,
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    started = True
                    yield {"delta": text}
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    tin = getattr(usage, "prompt_token_count", 0) or tin
                    tout = getattr(usage, "candidates_token_count", 0) or tout
            yield {"done": True, "tokens_input": tin, "tokens_output": tout}
            return
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            if started:
                logger.error("Gemini stream uzildi (client=%s): %s", label, e)
                yield {"error": "Javob oqimi uzildi."}
                return
            logger.warning("Gemini stream xato (client=%s): %s", label, e)
            continue

    logger.error("Gemini stream barcha keyda muvaffaqiyatsiz: %s", last_error)
    yield {"error": "AI javob bera olmadi. Iltimos, qaytadan urinib ko'ring."}


_ALLOWED_IMAGE_MIME = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)

# Audio whitelist'ning yagona manbasi services/storage.py (MIME_TO_EXT audio
# bo'limidan olinadi) — yangi format qo'shilsa bitta joyni yangilash kifoya.
_ALLOWED_AUDIO_MIME = AUDIO_MIMES


def generate_with_image(
    prompt: str,
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    system_instruction: str | None = None,
    response_schema: dict | None = None,
    max_tokens: int | None = 8192,
    temperature: float = 0.5,
) -> dict:
    """Multimodal: rasm + text generatsiya (ovqat tahlili uchun).

    Args:
        response_schema: Berilsa — Gemini kafolatlangan JSON qaytaradi.
            dict format: {"type": "object", "properties": {...}, "required": [...]}
        max_tokens: To'liq javob uchun 8192 (default). None — limit yo'q.
    """
    if not image_bytes:
        return {"error": "Rasm bo'sh."}

    if image_mime_type not in _ALLOWED_IMAGE_MIME:
        image_mime_type = "image/jpeg"

    return _generate(
        _build_multimodal_contents(prompt, image_bytes, image_mime_type),
        _build_config(
            system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
            response_schema=response_schema,
        ),
        error_label="multimodal",
        user_error="Rasmni tahlil qila olmadim. Qaytadan urinib ko'ring.",
    )


def generate_with_audio(
    prompt: str,
    audio_bytes: bytes,
    audio_mime_type: str = "audio/webm",
    system_instruction: str | None = None,
    response_schema: dict | None = None,
    max_tokens: int | None = 8192,
) -> dict:
    """Multimodal: audio + text generatsiya (STT va tibbiy yozuv uchun).

    Gemini native audio input'ni qabul qiladi — transcribe + tahlil bitta
    chaqiruvda.

    Args:
        prompt: Audio bilan birga yuboriladigan matn ko'rsatmasi
        audio_bytes: Audio fayl mazmuni
        audio_mime_type: "audio/webm" | "audio/mp3" | "audio/mp4" | "audio/wav" | "audio/ogg"
        response_schema: Berilsa — structured JSON qaytariladi
    """
    if not audio_bytes:
        return {"error": "Audio bo'sh."}

    if audio_mime_type not in _ALLOWED_AUDIO_MIME:
        audio_mime_type = "audio/webm"

    return _generate(
        _build_multimodal_contents(prompt, audio_bytes, audio_mime_type),
        _build_config(
            system_instruction,
            temperature=0.4,
            max_tokens=max_tokens,
            response_schema=response_schema,
        ),
        error_label="audio",
        user_error="Audio'ni tahlil qila olmadim. Qaytadan urinib ko'ring.",
    )
