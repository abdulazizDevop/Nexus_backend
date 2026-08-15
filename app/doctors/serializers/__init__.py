"""doctors serializerlari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.doctors.serializers import X` ishlashda davom etadi — doctors/views va
users/views importlari buzilmaydi.
"""

from .certificate import DoctorCertificateSerializer
from .listing import DoctorListSerializer, MarketplaceDoctorSerializer
from .patient import (
    AddByPhoneSerializer,
    DoctorPatientSerializer,
    PatientDetailSerializer,
    PatientWithHealthSerializer,
)
from .profile import DoctorProfileSerializer, DoctorProfileUpdateSerializer
from .slot import (
    AdminSlotSerializer,
    SlotCreateItemSerializer,
    SlotSerializer,
    SlotSyncRequestSerializer,
    SlotUpdateItemSerializer,
)
from .specialty import SpecialtySerializer

__all__ = [
    "SpecialtySerializer",
    "DoctorCertificateSerializer",
    "SlotSerializer",
    "AdminSlotSerializer",
    "SlotCreateItemSerializer",
    "SlotUpdateItemSerializer",
    "SlotSyncRequestSerializer",
    "DoctorProfileSerializer",
    "DoctorProfileUpdateSerializer",
    "DoctorListSerializer",
    "MarketplaceDoctorSerializer",
    "AddByPhoneSerializer",
    "DoctorPatientSerializer",
    "PatientWithHealthSerializer",
    "PatientDetailSerializer",
]
