"""auth bot — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.auth.bot import X` ishlaydi.
"""

from .handlers import (
    start_deeplink,
    start_no_args,
    receive_login_contact,
    receive_register_name,
    receive_register_sex,
    skip_register_referral,
    receive_register_referral,
    receive_register_contact,
    contact_text_fallback,
    handle_dose_taken,
)
from .runner import (
    main,
)

__all__ = [
    "start_deeplink",
    "start_no_args",
    "receive_login_contact",
    "receive_register_name",
    "receive_register_sex",
    "skip_register_referral",
    "receive_register_referral",
    "receive_register_contact",
    "contact_text_fallback",
    "handle_dose_taken",
    "main",
]
