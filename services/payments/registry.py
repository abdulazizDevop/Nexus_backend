"""Provider registry — kerakli provayderni faqat birinchi `get_provider`
chaqiriqda quradi (lazy). Shu sabab paytechuz gateway'lari import paytida
ishga tushmaydi va license tekshiruvi import'ni yiqitmaydi.

Yangi provider qo'shish: shu papkaga fayl yozish + `_PROVIDER_BUILDERS`
ro'yxatiga (key, builder, required_settings_keys) qo'shish.
"""

from collections.abc import Callable

from django.conf import settings

from .base import BasePaymentProvider
from .click import ClickProvider
from .payme import PaymeProvider

# (provider_name, builder, required_settings_keys)
_PROVIDER_BUILDERS: list[tuple[str, Callable[[], BasePaymentProvider], tuple[str, ...]]] = [
    ("payme", PaymeProvider, ("PAYME_ID", "PAYME_KEY")),
    ("click", ClickProvider, ("SERVICE_ID", "MERCHANT_ID", "SECRET_KEY")),
]

_PROVIDERS: dict[str, BasePaymentProvider] = {}


def _is_configured(name: str) -> bool:
    spec = next((s for s in _PROVIDER_BUILDERS if s[0] == name), None)
    if not spec:
        return False
    _, _, required = spec
    cfg = getattr(settings, "PAYTECHUZ", {}).get(name.upper(), {})
    return all(cfg.get(k) for k in required)


def get_provider(name: str) -> BasePaymentProvider:
    """Nomi bo'yicha provayderni qaytaradi (lazy build).

    - Kalitlar to'liq emas → ValueError ("not configured").
    - Birinchi marta — gateway quradi va cache qiladi.
    """
    if name in _PROVIDERS:
        return _PROVIDERS[name]

    spec = next((s for s in _PROVIDER_BUILDERS if s[0] == name), None)
    if not spec:
        raise ValueError(f"Unknown payment provider: {name!r}")

    if not _is_configured(name):
        raise ValueError(
            f"Payment provider '{name}' not configured. "
            f"Required settings.PAYTECHUZ[{name.upper()!r}] keys are missing."
        )

    _, builder, _ = spec
    provider = builder()
    _PROVIDERS[name] = provider
    return provider


def list_providers() -> list[str]:
    """Konfiguratsiya kalitlari to'liq bo'lgan provayderlar ro'yxati."""
    return [name for name, _, _ in _PROVIDER_BUILDERS if _is_configured(name)]
