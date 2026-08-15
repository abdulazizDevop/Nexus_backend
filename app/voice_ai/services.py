"""Voice AI — Gemini Live sessiya ma'lumotlari.

Ikki rejim (`settings.VOICE_USE_VERTEX`):
  • Vertex    → backend qisqa muddatli OAuth token + config qaytaradi; mobil
                to'g'ridan Vertex Live'ga ulanadi ($300/postpay, prepay devorisiz).
  • AI Studio → ephemeral token (config token ichiga "baked").

Ikkala rejimda ham AUDIO serverdan O'TMAYDI — mobil to'g'ridan Google'ga ulanadi,
server faqat qisqa kredential + config beradi.

Tashqi API (`create_live_session`) — dispatcher. Qolgani private:
  _session_system_instruction → persona + vaqt + bemor holati
  _live_config                → sessiya konfiguratsiyasi (ikkala rejim uchun yagona)
  _ephemeral_session          → AI Studio yo'li
  _vertex_session             → Vertex yo'li
"""

import random
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from .prompts import PERSONAS, build_system_instruction

# Ephemeral token TTL (AI Studio rejimi).
_TOKEN_TTL_MINUTES = 30
_NEW_SESSION_TTL_MINUTES = 2

# Vertex OAuth token uchun scope.
_VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_WEEKDAYS = {
    "uz": ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"],
    "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
}


# ─────────────────────────── Sozlamalar (env) ───────────────────────────


def _aistudio_model() -> str:
    return getattr(settings, "VOICE_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")


def _vertex_model() -> str:
    return getattr(settings, "VOICE_VERTEX_LIVE_MODEL", "gemini-live-2.5-flash-native-audio")


def _vertex_location() -> str:
    return getattr(settings, "VOICE_VERTEX_LOCATION", "us-central1")


def _use_vertex() -> bool:
    return bool(getattr(settings, "VOICE_USE_VERTEX", False))


# ─────────────────────────── Konfiguratsiya ───────────────────────────


def _current_time_line(lang: str = "uz") -> str:
    """Hozirgi Toshkent (UTC+5) vaqti — AI kun vaqtini hisobga olsin."""
    now = timezone.localtime()  # settings TIME_ZONE = Asia/Tashkent
    day = _WEEKDAYS.get(lang, _WEEKDAYS["uz"])[now.weekday()]
    stamp = now.strftime("%Y-%m-%d %H:%M")
    if lang == "ru":
        return (
            f"ТЕКУЩЕЕ ВРЕМЯ: {stamp}, {day} (Ташкент, UTC+5). "
            "Учитывай время суток (утро/день/вечер/ночь)."
        )
    return (
        f"HOZIRGI VAQT: {stamp}, {day} (Toshkent, UTC+5). "
        "Kun vaqtini hisobga ol (ertalab/kunduzi/kechqurun/tun)."
    )


def _persona(persona: str) -> tuple[str, str]:
    """(kalit, ovoz) — noto'g'ri kalit berilsa birinchi personaga qaytadi."""
    key = persona if persona in PERSONAS else next(iter(PERSONAS))
    return key, PERSONAS[key]["voice"]


def _session_system_instruction(user, persona: str, lang: str) -> str:
    """Persona ko'rsatmasi + hozirgi vaqt + bemor holati → to'liq system-instruction.

    Bemor konteksti xato bersa — sessiya buzilmaydi (bo'sh qo'shiladi).
    """
    from .context import build_patient_context

    instruction = f"{build_system_instruction(persona, lang)}\n\n{_current_time_line(lang)}"
    try:
        patient_context = build_patient_context(user)
    except Exception:  # noqa: BLE001 — kontekst xatosi sessiyani buzmasin
        patient_context = ""
    if patient_context:
        instruction = f"{instruction}\n\n{patient_context}"
    return instruction


def _live_config(voice: str, system_instruction: str) -> dict:
    """Live sessiya konfiguratsiyasi — ikkala rejim uchun YAGONA manba.

    Transkript (text) o'chirilgan — faqat ovoz (tezroq). Thinking o'chirilgan
    (thinking_budget=0) — javob ~35% tez.
    """
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": system_instruction,
        "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}},
        "temperature": 1.2,
        "thinking_config": {"thinking_budget": 0},
        "session_resumption": {},
    }


def _persona_live_config(user, persona: str, lang: str) -> tuple[str, str, dict]:
    """(kalit, ovoz, config) — ikkala sessiya rejimi uchun umumiy prelude."""
    key, voice = _persona(persona)
    config = _live_config(voice, _session_system_instruction(user, persona, lang))
    return key, voice, config


# ─────────────────────────── AI Studio (ephemeral) ───────────────────────────


def _pick_api_key() -> str:
    """GEMINI_API_KEY_* rotatsiyasidan bittasi (services.gemini)."""
    from services.gemini import _get_api_keys

    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY topilmadi")
    return random.choice(keys)


def _ephemeral_session(user, persona: str, lang: str) -> dict:
    """AI Studio: uses=1 ephemeral token — config token ichiga baked."""
    from google import genai

    key, voice, config = _persona_live_config(user, persona, lang)
    model = _aistudio_model()

    now = timezone.now()
    client = genai.Client(api_key=_pick_api_key(), http_options={"api_version": "v1alpha"})
    token = client.auth_tokens.create(
        config={
            "uses": 1,
            "expire_time": now + timedelta(minutes=_TOKEN_TTL_MINUTES),
            "new_session_expire_time": now + timedelta(minutes=_NEW_SESSION_TTL_MINUTES),
            "live_connect_constraints": {"model": model, "config": config},
            "http_options": {"api_version": "v1alpha"},
        }
    )
    return {
        "mode": "ai_studio",
        "token": token.name,
        "model": model,
        "voice": voice,
        "persona": key,
        "lang": lang,
    }


# ─────────────────────────── Vertex (client-direct OAuth) ───────────────────────────


def _mint_access_token() -> tuple[str, datetime]:
    """ADC (service account / gcloud) dan qisqa muddatli OAuth access token + expiry (UTC)."""
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(scopes=_VERTEX_SCOPES)
    creds.refresh(Request())
    expiry = creds.expiry or (datetime.now(dt_timezone.utc) + timedelta(minutes=55))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=dt_timezone.utc)
    return creds.token, expiry


def _vertex_session(user, persona: str, lang: str) -> dict:
    """Vertex: qisqa OAuth token + ulanish ma'lumoti + config (client sozlash uchun)."""
    key, voice, config = _persona_live_config(user, persona, lang)
    project = getattr(settings, "GOOGLE_CLOUD_PROJECT", "")
    location = _vertex_location()
    model = _vertex_model()
    token, expiry = _mint_access_token()

    return {
        "mode": "vertex",
        "access_token": token,
        "expires_at": expiry.isoformat(),
        "endpoint": (
            f"wss://{location}-aiplatform.googleapis.com/ws/"
            "google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent"
        ),
        "project": project,
        "location": location,
        "model": model,
        "model_path": f"projects/{project}/locations/{location}/publishers/google/models/{model}",
        "voice": voice,
        "persona": key,
        "lang": lang,
        "config": config,
    }


# ─────────────────────────── Public API ───────────────────────────


def create_live_session(user, persona: str, lang: str = "uz") -> dict:
    """Live ovoz sessiyasi ma'lumotlari — rejimga qarab (`VOICE_USE_VERTEX`).

    Vertex   → {mode, access_token, expires_at, endpoint, project, location,
                model, model_path, voice, persona, lang, config}
    AI Studio → {mode, token, model, voice, persona, lang}
    """
    if _use_vertex():
        return _vertex_session(user, persona, lang)
    return _ephemeral_session(user, persona, lang)
