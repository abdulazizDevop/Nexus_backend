from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin


class SpecialtySerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Mutaxassislik — `name` 3 tilli JSON.

    O'qish:
      - `?lang=ru` → `name: "Кардиолог"` (string)
      - `?include_translations=1` (admin) → `name: {uz, ru, cyr}` (dict)
    Yozish (admin):
      - `{"name": {"uz": "Kardiolog", "ru": "Кардиолог", "cyr": "Кардиолог"}, "icon": "❤️"}`
    """

    translatable_fields = ["name"]

    class Meta:
        model = Specialty
        fields = ["id", "name", "icon"]


