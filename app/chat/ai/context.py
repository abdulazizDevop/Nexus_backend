"""Bemor konteksti — diet_ai build_user_context'ni reuse qiladi (xavfsiz)."""


def build_patient_context(patient_user) -> str:
    """Bemor profil/salomatlik kontekstini qaytaradi; xato bo'lsa '' (javobni buzmaydi)."""
    try:
        from app.diet_ai.services import build_user_context

        return build_user_context(patient_user)
    except Exception:
        return ""
