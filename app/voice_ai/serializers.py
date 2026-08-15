from rest_framework import serializers

from .prompts import DEFAULT_LANG, DEFAULT_PERSONA, LANGUAGES, PERSONAS


class LiveTokenRequestSerializer(serializers.Serializer):
    """Live ovoz sessiyasi uchun token so'rovi."""

    persona = serializers.ChoiceField(
        choices=list(PERSONAS.keys()), default=DEFAULT_PERSONA
    )
    lang = serializers.ChoiceField(
        choices=[lang["id"] for lang in LANGUAGES], default=DEFAULT_LANG
    )
