from rest_framework import status
from django.utils import timezone

from app.health_packages.models import HealthIndicatorType
from tests.base import BaseAPITestCase


class DailyCheckupTests(BaseAPITestCase):
    """Health Packages — Kunlik holat nazorati"""

    def test_create_checkup(self):
        """POST /packages/daily-checkup/ — bugungi holat kiritish"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/packages/daily-checkup/",
            {
                "status": "good",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_checkup_duplicate_updates(self):
        """POST /packages/daily-checkup/ — ikki marta kiritsa yangilaydi"""
        self.auth_as_patient()
        self.client.post("/api/v1/packages/daily-checkup/", {"status": "good"})
        resp = self.client.post("/api/v1/packages/daily-checkup/", {"status": "bad"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "bad")

    def test_create_checkup_invalid_status(self):
        """POST /packages/daily-checkup/ — noto'g'ri status"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/packages/daily-checkup/",
            {
                "status": "invalid",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_today_me_empty(self):
        """GET /packages/daily-checkup/today-me/ — kiritilmagan bo'lsa 204"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/packages/daily-checkup/today-me/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_today_me_with_data(self):
        """GET /packages/daily-checkup/today-me/ — kiritilgan"""
        self.auth_as_patient()
        self.client.post("/api/v1/packages/daily-checkup/", {"status": "normal"})
        resp = self.client.get("/api/v1/packages/daily-checkup/today-me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "normal")

    def test_today_me_update(self):
        """PUT /packages/daily-checkup/today-me/update/ — yangilash"""
        self.auth_as_patient()
        self.client.post("/api/v1/packages/daily-checkup/", {"status": "good"})
        resp = self.client.put(
            "/api/v1/packages/daily-checkup/today-me/update/",
            {"status": "bad"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "bad")

    def test_today_me_update_not_created(self):
        """PUT /packages/daily-checkup/today-me/update/ — kiritilmagan bo'lsa 404"""
        self.auth_as_patient()
        resp = self.client.put(
            "/api/v1/packages/daily-checkup/today-me/update/",
            {"status": "bad"},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated(self):
        """POST /packages/daily-checkup/ — login qilmagan"""
        resp = self.client.post("/api/v1/packages/daily-checkup/", {})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class HealthIndicatorTypeTests(BaseAPITestCase):
    """Health Packages — Ko'rsatkich turlari"""

    def test_list_types(self):
        """GET /packages/indicator-types/ — ro'yxat (barcha rollar to'liq ko'radi)"""
        # Endi cheklov yo'q — patient ham system_key bor turlarni (seed: Diet AI
        # macros) ko'radi. Test seed'lardan mustaqil: o'zimiz yaratgan
        # turni tekshiramiz.
        created = HealthIndicatorType.objects.create(name="Qadam", unit="qadam")
        self.auth_as_patient()
        resp = self.client.get("/api/v1/packages/indicator-types/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # List endpoint paginatsiyalangan (DEFAULT_PAGINATION_CLASS) —
        # natija {count, next, previous, results} shaklida.
        rows = resp.data["results"]
        ids = [row["id"] for row in rows]
        self.assertIn(created.id, ids)

    def test_create_type_admin(self):
        """POST /packages/indicator-types/ — admin yaratadi"""
        self.auth_as_admin()
        # Admin `name`'ni 3 tilli dict shaklida yuboradi (TranslatableFieldsMixin
        # asosiy write yo'li). String shortcut ham qabul qilinadi, lekin dict —
        # production'da admin form'i yuboradigan haqiqiy format.
        resp = self.client.post(
            "/api/v1/packages/indicator-types/",
            {
                "name": {"uz": "Yurak urishi", "ru": "Пульс", "cyr": "Юрак уриши"},
                "unit": "bpm",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_create_type_patient_forbidden(self):
        """POST /packages/indicator-types/ — patient yarata olmaydi"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/packages/indicator-types/",
            {
                "name": "Test",
                "unit": "x",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_includes_category_and_manual_entry(self):
        """GET /packages/indicator-types/ — har turda category + manual_entry qaytadi"""
        created = HealthIndicatorType.objects.create(
            name="Vazn", unit="kg", category="manual", manual_entry=True
        )
        self.auth_as_patient()
        resp = self.client.get("/api/v1/packages/indicator-types/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        row = next(r for r in resp.data["results"] if r["id"] == created.id)
        self.assertEqual(row["category"], "manual")
        self.assertTrue(row["manual_entry"])

    def test_create_type_default_category_manual(self):
        """POST (admin, category bermasa) — default category=manual, manual_entry=True"""
        self.auth_as_admin()
        resp = self.client.post(
            "/api/v1/packages/indicator-types/",
            {
                "name": {"uz": "Xolesterin", "ru": "Холестерин", "cyr": "Холестерин"},
                "unit": "mmol/L",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["category"], "manual")
        self.assertTrue(resp.data["manual_entry"])

    def test_admin_sets_category_and_manual_entry(self):
        """POST (admin) — category=diet + manual_entry=False saqlanadi va o'qiladi"""
        self.auth_as_admin()
        resp = self.client.post(
            "/api/v1/packages/indicator-types/",
            {
                "name": {"uz": "Test tur", "ru": "x", "cyr": "x"},
                "unit": "u",
                "category": "diet",
                "manual_entry": False,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["category"], "diet")
        self.assertFalse(resp.data["manual_entry"])
        obj = HealthIndicatorType.objects.get(id=resp.data["id"])
        self.assertEqual(obj.category, "diet")
        self.assertFalse(obj.manual_entry)


class HealthIndicatorTests(BaseAPITestCase):
    """Health Packages — Ko'rsatkichlar CRUD"""

    def setUp(self):
        super().setUp()
        self.ind_type = HealthIndicatorType.objects.create(name="Qadam", unit="qadam")

    def test_create_indicator(self):
        """POST /packages/indicators/ — ko'rsatkich qo'shish"""
        self.auth_as_patient()
        today = timezone.now().date()
        resp = self.client.post(
            "/api/v1/packages/indicators/",
            {
                "indicator_type": self.ind_type.id,
                "value": 8500,
                "date": str(today),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_indicator_multiple_per_day_allowed(self):
        """POST /packages/indicators/ — event sourcing: har POST yangi event yaratadi."""
        from app.health_packages.models import HealthIndicator
        user = self.auth_as_patient()
        first = self.client.post(
            "/api/v1/packages/indicators/",
            {"indicator_type": self.ind_type.id, "value": 5000},
        )
        second = self.client.post(
            "/api/v1/packages/indicators/",
            {"indicator_type": self.ind_type.id, "value": 8500},
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        # Ikkita alohida event yaratilganini tekshirish
        self.assertEqual(
            HealthIndicator.objects.filter(user=user, indicator_type=self.ind_type).count(),
            2,
        )

    def test_today_me(self):
        """GET /packages/indicators/today-me/ — bugungi ko'rsatkichlar"""
        user = self.auth_as_patient()
        from app.health_packages.models import HealthIndicator

        HealthIndicator.objects.create(
            user=user,
            indicator_type=self.ind_type,
            value=7000,
            date=timezone.now().date(),
        )
        resp = self.client.get("/api/v1/packages/indicators/today-me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_list_grouped_by_date(self):
        """GET /packages/indicators/ — date bo'yicha guruhlangan"""
        user = self.auth_as_patient()
        from app.health_packages.models import HealthIndicator

        today = timezone.now().date()
        HealthIndicator.objects.create(
            user=user,
            indicator_type=self.ind_type,
            value=5000,
            date=today,
        )
        resp = self.client.get("/api/v1/packages/indicators/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn(str(today), resp.data)

    def test_unauthenticated(self):
        """GET /packages/indicators/ — login qilmagan"""
        resp = self.client.get("/api/v1/packages/indicators/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
