"""auth serializers — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.auth.serializers import X` ishlaydi.
"""

from .auth import (
    AuthRequestSerializer,
    AuthVerifySerializer,
    CompleteRegistrationSerializer,
)
from .link import (
    LinkDoctorSerializer,
)
from .logout import (
    LogoutSerializer,
)
from .account_deletion import (
    AccountDeletionRequestSerializer,
)
from .common import normalize_phone  # noqa: F401

__all__ = [
    "AuthRequestSerializer",
    "AuthVerifySerializer",
    "CompleteRegistrationSerializer",
    "LinkDoctorSerializer",
    "LogoutSerializer",
    "AccountDeletionRequestSerializer",
    "normalize_phone",
]
