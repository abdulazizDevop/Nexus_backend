"""doctors view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.doctors.views import X` ishlashda davom etadi — urls.py buzilmaydi.
"""

from .certificate import DoctorCertificateViewSet
from .profile import DoctorProfileViewSet
from .slots import (
    AdminDoctorSlotsView,
    DoctorMeSlotsSyncView,
    DoctorMeSlotsView,
    PublicDoctorSlotsView,
)
from .specialty import SpecialtyViewSet

__all__ = [
    "SpecialtyViewSet",
    "DoctorProfileViewSet",
    "DoctorCertificateViewSet",
    "DoctorMeSlotsView",
    "DoctorMeSlotsSyncView",
    "AdminDoctorSlotsView",
    "PublicDoctorSlotsView",
]
