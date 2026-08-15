"""Chat ovozli xabar STT — Gemini orqali on-demand transkripsiya.

Faqat bemor ovozlari (doctor o'qishi uchun). `services.gemini.generate_with_audio`
ishlatadi (audio+text multimodal, google-genai SDK). Sinxron — view'dan chaqiriladi,
natija Message.transcript'ga saqlanadi (qayta so'rovda Gemini chaqirilmaydi).
"""

import logging

from services.gemini import generate_with_audio
from services.storage import download_file_bytes

logger = logging.getLogger(__name__)

# Transcribator (developer/transcribator) namunasidan moslangan — o'zbek/rus,
# tarjimasiz, faqat transkript matni.
TRANSCRIBE_PROMPT = """
Sen professional transkripsiya mutaxassisisan. Yuborilgan ovozli xabarni TO'LIQ
va YUQORI ANIQLIKda matnga aylantir.

Qoidalar:
- Audio ISTALGAN tilda bo'lishi mumkin (o'zbek, rus, ingliz, qozoq, tojik,
  qirg'iz va boshqalar; ba'zida bir nechta til aralash). Tilni AVTOMATIK aniqla
  va nutqni ASL TILIDA, asl so'zlar bilan yoz. HECH QACHON TARJIMA QILMA.
- Aralash tilda gaplashilsa — har bir qismni o'z tilida yoz.
- Hech bir jumlani tashlab ketma, boshidan oxirigacha yoz.
- Tinish belgilarini to'g'ri qo'y.
- Agar so'z aniq eshitilmasa [noaniq] deb belgila.
- Sonlar, ismlar, dori nomlari va tibbiy atamalarni aniq yoz.
- Javobingda FAQAT transkript matni bo'lsin — hech qanday sarlavha, izoh,
  muqaddima, til nomi yoki xulosa qo'shma.
""".strip()


def transcribe_audio_message(message) -> str:
    """Message'ning ovozli faylini Gemini orqali transkripsiya qiladi.

    Returns: transkript matni.
    Raises: RuntimeError — fayl yo'q / yuklab bo'lmadi / Gemini xatosi / bo'sh javob.
    """
    if not message.file_key:
        raise RuntimeError("Ovozli xabarda fayl yo'q.")

    audio_bytes, content_type = download_file_bytes(message.file_key)
    if not audio_bytes:
        raise RuntimeError("Audio fayl bo'sh.")

    mime = message.file_type or content_type or "audio/mp4"
    result = generate_with_audio(
        TRANSCRIBE_PROMPT,
        audio_bytes,
        audio_mime_type=mime,
        max_tokens=None,  # to'liq transkript — limit yo'q
    )
    if "error" in result:
        raise RuntimeError(result["error"])

    text = (result.get("text") or "").strip()
    if not text:
        raise RuntimeError("Transkript bo'sh qaytdi.")
    return text
