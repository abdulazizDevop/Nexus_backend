from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import UserFactory


class BaseAPITestCase(APITestCase):
    """Barcha testlar uchun base class"""

    def setUp(self):
        self.client = APIClient()
        # DRF throttling Redis cache'ga yozadi — test'lar orasida tozalaymiz,
        # aks holda ko'p test bir IP'dan kelganda 429 chiqaradi.
        cache.clear()

    def authenticate(self, user):
        """JWT token bilan authenticate qilish.

        RefreshToken instance qaytaradi (eski testlar `str(refresh)` qilishi uchun).
        Phase 3 mos kelishi uchun token'ga scope va profile ID'lar yoziladi —
        production'dagi `create_tokens_for_user` bilan bir xil claim'lar.
        """
        refresh = RefreshToken.for_user(user)
        active_role = user.active_role or user.role
        refresh["active_role"] = active_role
        refresh["scope"] = active_role
        try:
            refresh["patient_id"] = user.patient_profile.id
        except Exception:
            refresh["patient_id"] = None
        try:
            refresh["doctor_id"] = user.doctor_profile.id
        except Exception:
            refresh["doctor_id"] = None
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return refresh

    def create_patient(self, **kwargs):
        user = UserFactory.create_patient(**kwargs)
        return user

    def create_doctor(self, **kwargs):
        user = UserFactory.create_doctor(**kwargs)
        return user

    def create_admin(self, admin_type="super", **kwargs):
        return UserFactory.create_admin(admin_type=admin_type, **kwargs)

    def create_seller(self, **kwargs):
        return UserFactory.create_seller(**kwargs)

    def auth_as_patient(self, **kwargs):
        user = self.create_patient(**kwargs)
        self.authenticate(user)
        return user

    def auth_as_doctor(self, **kwargs):
        user = self.create_doctor(**kwargs)
        self.authenticate(user)
        return user

    def auth_as_admin(self, admin_type="super", **kwargs):
        user = self.create_admin(admin_type=admin_type, **kwargs)
        self.authenticate(user)
        return user
