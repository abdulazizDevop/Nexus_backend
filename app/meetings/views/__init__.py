"""meetings views — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.meetings.views import X` ishlaydi — urls.py buzilmaydi.
"""

from .patient import (
    PatientAppointmentViewSet,
)
from .doctor import (
    DoctorAppointmentViewSet,
)
from .admin import (
    AdminAppointmentViewSet,
)
from .consultation import (
    ConsultationViewSet,
)

__all__ = [
    "PatientAppointmentViewSet",
    "DoctorAppointmentViewSet",
    "AdminAppointmentViewSet",
    "ConsultationViewSet",
]
