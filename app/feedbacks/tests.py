from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from app.doctors.models import DoctorProfile, Specialty
from app.feedbacks.models import Review
from app.meetings.models import Appointment

User = get_user_model()


class ReviewModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Kardiolog", icon="❤️")

        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )

        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )
        cls.other_patient = User.objects.create_user(
            phone="+998903333333", full_name="Patient Two", role=User.Role.PATIENT
        )

    def _make_appointment(self, status=Appointment.Status.COMPLETED, patient=None):
        return Appointment.objects.create(
            patient=patient or self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=status,
        )

    def test_create_review_for_completed_appointment_succeeds(self):
        appt = self._make_appointment()
        review = Review.objects.create(appointment=appt, rating=5, comment="Ajoyib!")
        self.assertEqual(review.doctor, self.doctor)
        self.assertEqual(review.patient, self.patient)
        self.assertEqual(review.rating, 5)

    def test_create_review_for_pending_appointment_fails(self):
        appt = self._make_appointment(status=Appointment.Status.PENDING)
        with self.assertRaises(ValidationError) as ctx:
            Review.objects.create(appointment=appt, rating=5)
        self.assertIn("appointment", ctx.exception.message_dict)

    def test_create_review_for_approved_appointment_fails(self):
        appt = self._make_appointment(status=Appointment.Status.APPROVED)
        with self.assertRaises(ValidationError):
            Review.objects.create(appointment=appt, rating=5)

    def test_rating_must_be_between_1_and_5(self):
        appt = self._make_appointment()
        for bad in (0, 6, 10):
            with self.assertRaises(ValidationError):
                Review.objects.create(appointment=appt, rating=bad)

    def test_one_review_per_appointment(self):
        appt = self._make_appointment()
        Review.objects.create(appointment=appt, rating=4)
        with self.assertRaises((IntegrityError, ValidationError)):
            with transaction.atomic():
                Review.objects.create(appointment=appt, rating=5)

    def test_doctor_and_patient_are_auto_filled_from_appointment(self):
        appt = self._make_appointment()
        review = Review(appointment=appt, rating=3)
        review.save()
        self.assertEqual(review.doctor_id, appt.doctor_id)
        self.assertEqual(review.patient_id, appt.patient_id)

    def test_doctor_rating_property_reflects_reviews(self):
        appt1 = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )
        appt2 = Appointment.objects.create(
            patient=self.other_patient,
            doctor=self.doctor,
            date=date(2026, 5, 2),
            start_time=time(11, 0),
            end_time=time(11, 30),
            status=Appointment.Status.COMPLETED,
        )
        Review.objects.create(appointment=appt1, rating=5)
        Review.objects.create(appointment=appt2, rating=3)

        self.assertEqual(self.doctor.rating, 4.0)
        self.assertEqual(self.doctor.total_reviews, 2)

    def test_comment_optional(self):
        appt = self._make_appointment()
        review = Review.objects.create(appointment=appt, rating=4)
        self.assertEqual(review.comment, "")


class ReviewAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Pediatr", icon="👶")

        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor_user.active_role = User.Role.DOCTOR
        cls.doctor_user.save(update_fields=["active_role"])
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )

        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )
        cls.other_patient = User.objects.create_user(
            phone="+998903333333", full_name="Patient Two", role=User.Role.PATIENT
        )

    def _make_appointment(self, status=Appointment.Status.COMPLETED, patient=None):
        return Appointment.objects.create(
            patient=patient or self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=status,
        )

    # --- POST /reviews/ ---

    def test_patient_creates_review_for_completed_appointment(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5, "comment": "Ajoyib shifokor!"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.data["rating"], 5)
        self.assertEqual(response.data["comment"], "Ajoyib shifokor!")
        self.assertEqual(response.data["doctor_id"], self.doctor.id)
        # Anonim format: ism + familiyaning birinchi harfi
        self.assertEqual(response.data["patient_name"], "Patient O.")
        self.assertFalse(response.data["is_edited"])

    def test_create_review_fails_for_pending_appointment(self):
        appt = self._make_appointment(status=Appointment.Status.PENDING)
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        # Custom exception handler "{field}: {message}" formatida qaytaradi
        self.assertIn("appointment_id", response.json()["detail"])

    def test_create_review_fails_for_other_patient_appointment(self):
        """Patient boshqa bemorning qabuli uchun review yoza olmasligi kerak."""
        appt = self._make_appointment(patient=self.other_patient)
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_review_fails_when_already_reviewed(self):
        appt = self._make_appointment()
        Review.objects.create(appointment=appt, rating=4, comment="oldingisi")
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_doctor_cannot_create_review(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.doctor_user)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_create_review(self):
        appt = self._make_appointment()
        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_rating_validation_via_api(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        for bad in (0, 6, 100):
            response = self.client.post(
                reverse("review-list"),
                {"appointment_id": appt.id, "rating": bad},
                format="json",
            )
            self.assertEqual(response.status_code, 400, f"rating={bad}")

    # --- GET /reviews/?doctor_id=N ---

    def test_list_reviews_filtered_by_doctor(self):
        appt1 = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )
        Review.objects.create(appointment=appt1, rating=5, comment="A")

        self.client.force_authenticate(user=self.patient)
        response = self.client.get(reverse("review-list"), {"doctor_id": self.doctor.id})

        self.assertEqual(response.status_code, 200)
        results = response.json().get("results", response.json())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["rating"], 5)

    # --- GET /reviews/me/ ---

    def test_me_returns_only_own_reviews(self):
        my_appt = self._make_appointment()
        other_appt = Appointment.objects.create(
            patient=self.other_patient,
            doctor=self.doctor,
            date=date(2026, 5, 2),
            start_time=time(11, 0),
            end_time=time(11, 30),
            status=Appointment.Status.COMPLETED,
        )
        Review.objects.create(appointment=my_appt, rating=5)
        Review.objects.create(appointment=other_appt, rating=2)

        self.client.force_authenticate(user=self.patient)
        response = self.client.get(reverse("review-me"))

        self.assertEqual(response.status_code, 200)
        results = response.json().get("results", response.json())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["rating"], 5)


class ReviewCooldownTests(APITestCase):
    """30 kunlik cooldown — shu doctor uchun bir patient maks 1 review."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Stomatolog", icon="🦷")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.other_doctor_user = User.objects.create_user(
            phone="+998904444444", full_name="Doctor Two", role=User.Role.DOCTOR
        )
        cls.other_doctor = DoctorProfile.objects.create(
            user=cls.other_doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )

    def _make_appointment(self, doctor=None, day=1):
        return Appointment.objects.create(
            patient=self.patient,
            doctor=doctor or self.doctor,
            date=date(2026, 5, day),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )

    def test_recent_review_blocks_new_one_for_same_doctor(self):
        appt1 = self._make_appointment(day=1)
        appt2 = self._make_appointment(day=2)
        Review.objects.create(appointment=appt1, rating=5)

        self.client.force_authenticate(user=self.patient)
        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt2.id, "rating": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("yaqinda review qoldirgansiz", str(body))

    def test_old_review_does_not_block(self):
        from datetime import timedelta

        from django.utils import timezone

        appt1 = self._make_appointment(day=1)
        old = Review.objects.create(appointment=appt1, rating=5)
        Review.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )

        appt2 = self._make_appointment(day=2)

        self.client.force_authenticate(user=self.patient)
        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt2.id, "rating": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())

    def test_cooldown_is_per_doctor_not_global(self):
        appt1 = self._make_appointment(doctor=self.doctor, day=1)
        Review.objects.create(appointment=appt1, rating=5)

        appt2 = self._make_appointment(doctor=self.other_doctor, day=2)

        self.client.force_authenticate(user=self.patient)
        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt2.id, "rating": 4},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())


class ReviewTagTests(APITestCase):
    """Tag tizimi — sentiment validatsiya, tag list endpoint, top_tags stats."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Dermatolog", icon="🧴")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )

    def _make_appointment(self, day=1):
        return Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, day),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )

    def test_tag_list_endpoint_returns_active_tags(self):
        # Migration seed bilan 12 ta tag bor (7 positive + 5 negative)
        self.client.force_authenticate(user=self.patient)

        response = self.client.get(reverse("review-tag-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 12)

        response = self.client.get(reverse("review-tag-list"), {"sentiment": "positive"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 7)
        self.assertTrue(all(t["sentiment"] == "positive" for t in response.data))

        response = self.client.get(reverse("review-tag-list"), {"sentiment": "negative"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)

    def test_create_review_with_positive_tags_succeeds(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {
                "appointment_id": appt.id,
                "rating": 5,
                "tag_slugs": ["explains_well", "attentive", "recommend"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        slugs = {t["slug"] for t in response.data["tags"]}
        self.assertEqual(slugs, {"explains_well", "attentive", "recommend"})

    def test_create_review_high_rating_with_negative_tag_fails(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5, "tag_slugs": ["late"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("positive", str(response.json()))

    def test_create_review_low_rating_with_positive_tag_fails(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 2, "tag_slugs": ["explains_well"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("negative", str(response.json()))

    def test_unknown_tag_slug_fails(self):
        appt = self._make_appointment()
        self.client.force_authenticate(user=self.patient)

        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5, "tag_slugs": ["does_not_exist"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_stats_includes_top_tags(self):
        from app.feedbacks.models import ReviewTag

        appt1 = self._make_appointment(day=1)
        appt2 = Appointment.objects.create(
            patient=User.objects.create_user(
                phone="+998905555555",
                full_name="Patient Two",
                role=User.Role.PATIENT,
            ),
            doctor=self.doctor,
            date=date(2026, 5, 2),
            start_time=time(11, 0),
            end_time=time(11, 30),
            status=Appointment.Status.COMPLETED,
        )

        r1 = Review.objects.create(appointment=appt1, rating=5)
        r2 = Review.objects.create(appointment=appt2, rating=5)

        explains_well = ReviewTag.objects.get(slug="explains_well")
        attentive = ReviewTag.objects.get(slug="attentive")
        r1.tags.set([explains_well, attentive])
        r2.tags.set([explains_well])

        self.client.force_authenticate(user=self.patient)
        response = self.client.get(
            reverse("review-list"), {"doctor_id": self.doctor.id}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()

        top_tags = body["stats"]["top_tags"]
        slugs = [t["slug"] for t in top_tags]
        self.assertIn("explains_well", slugs)
        self.assertIn("attentive", slugs)

        explains = next(t for t in top_tags if t["slug"] == "explains_well")
        self.assertEqual(explains["count"], 2)
        self.assertEqual(explains["percent"], 100)


class ReviewEditDeleteTests(APITestCase):
    """24h ichida edit/delete, keyin yopiq."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Urolog", icon="💧")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )
        cls.other_patient = User.objects.create_user(
            phone="+998903333333", full_name="Patient Two", role=User.Role.PATIENT
        )

    def _make_review(self, patient=None):
        appt = Appointment.objects.create(
            patient=patient or self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )
        return Review.objects.create(appointment=appt, rating=5, comment="boshlang'ich")

    def test_patient_can_edit_within_window(self):
        review = self._make_review()
        self.client.force_authenticate(user=self.patient)

        response = self.client.patch(
            reverse("review-detail", kwargs={"pk": review.pk}),
            {"rating": 4, "comment": "tahrirlangan"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.data["rating"], 4)
        self.assertEqual(response.data["comment"], "tahrirlangan")
        self.assertTrue(response.data["is_edited"])

    def test_patient_can_delete_within_window(self):
        review = self._make_review()
        self.client.force_authenticate(user=self.patient)

        response = self.client.delete(
            reverse("review-detail", kwargs={"pk": review.pk})
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())

    def test_edit_after_window_fails(self):
        from datetime import timedelta

        from django.utils import timezone

        review = self._make_review()
        Review.objects.filter(pk=review.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        self.client.force_authenticate(user=self.patient)
        response = self.client.patch(
            reverse("review-detail", kwargs={"pk": review.pk}),
            {"rating": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("24 soat o'tgan", str(response.json()))

    def test_delete_after_window_fails(self):
        from datetime import timedelta

        from django.utils import timezone

        review = self._make_review()
        Review.objects.filter(pk=review.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        self.client.force_authenticate(user=self.patient)
        response = self.client.delete(
            reverse("review-detail", kwargs={"pk": review.pk})
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_other_patient_cannot_edit(self):
        review = self._make_review()
        self.client.force_authenticate(user=self.other_patient)

        response = self.client.patch(
            reverse("review-detail", kwargs={"pk": review.pk}),
            {"rating": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_edit_changes_tags(self):
        from app.feedbacks.models import ReviewTag

        review = self._make_review()
        review.tags.set(ReviewTag.objects.filter(slug__in=["explains_well", "attentive"]))

        self.client.force_authenticate(user=self.patient)
        response = self.client.patch(
            reverse("review-detail", kwargs={"pk": review.pk}),
            {"tag_slugs": ["recommend"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        slugs = {t["slug"] for t in response.data["tags"]}
        self.assertEqual(slugs, {"recommend"})


class AutoCompleteAppointmentTaskTests(TestCase):
    """auto_complete_appointments task: end + 2h dan keyin COMPLETED."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Ginekolog", icon="🩷")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor One", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )

    def test_auto_complete_marks_old_approved_as_completed(self):
        from datetime import timedelta

        from django.utils import timezone

        from app.meetings.tasks import auto_complete_appointments

        # Kechagi appointment — vaqti 3 soat oldin tugagan
        yesterday = (timezone.now() - timedelta(days=1)).date()
        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=yesterday,
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.APPROVED,
        )

        result = auto_complete_appointments()

        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.COMPLETED)
        self.assertGreaterEqual(result, 1)

    def test_auto_complete_skips_recent_approved(self):
        from datetime import timedelta

        from django.utils import timezone

        from app.meetings.tasks import auto_complete_appointments

        # Appointment vaqti hali tugamagan — end 3 soat keyin (grace 2h dan ko'p).
        # MUHIM: task `datetime.combine(appt.date, appt.end_time)` qiladi, shuning
        # uchun saqlanadigan (date, end_time) juftligi aynan `end_dt` ni qayta
        # tiklashi shart — aks holda yarim tun chegarasida start/end turli kunlarga
        # tushib, end vaqti o'tmishda hisoblanib qoladi (flaky). Shu sababli date
        # ni end_dt.date() ga bog'laymiz va start ni ham shu kun ichida ushlaymiz.
        # localtime (Asia/Tashkent) — task `datetime.combine(date, end_time, tz)`
        # bilan qayta tiklaganda mos kelsin (Appointment vaqtlari local saqlanadi;
        # timezone.now() UTC bo'lib 5 soat siljishni keltirardi → flaky complete).
        end_dt = timezone.localtime(timezone.now()) + timedelta(hours=3)
        start_dt = end_dt - timedelta(minutes=30)
        if start_dt.date() != end_dt.date():
            # start oldingi kunga tushib qolsa, start ni end bilan bir kunga keltiramiz
            start_dt = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=end_dt.date(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            status=Appointment.Status.APPROVED,
        )

        auto_complete_appointments()

        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.APPROVED)

    def test_auto_complete_does_not_touch_other_statuses(self):
        from datetime import timedelta

        from django.utils import timezone

        from app.meetings.tasks import auto_complete_appointments

        yesterday = (timezone.now() - timedelta(days=1)).date()

        pending = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=yesterday,
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.PENDING,
        )
        cancelled = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=yesterday,
            start_time=time(11, 0),
            end_time=time(11, 30),
            status=Appointment.Status.CANCELLED,
        )

        auto_complete_appointments()

        pending.refresh_from_db()
        cancelled.refresh_from_db()
        self.assertEqual(pending.status, Appointment.Status.PENDING)
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True
)
class NotifyDoctorOnNewReviewTests(APITestCase):
    """Patient review yaratganda doctor'ga NEW_REVIEW notification yaratiladi."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Oftalmolog", icon="👁️")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111",
            full_name="Doctor Bek",
            role=User.Role.DOCTOR,
            active_role=User.Role.DOCTOR,
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        cls.patient = User.objects.create_user(
            phone="+998902222222", full_name="Patient One", role=User.Role.PATIENT
        )

    def test_review_creation_notifies_doctor(self):
        from app.notifications.models import Notification

        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 1),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.COMPLETED,
        )

        self.assertEqual(
            Notification.objects.filter(user=self.doctor_user).count(), 0
        )

        self.client.force_authenticate(user=self.patient)
        response = self.client.post(
            reverse("review-list"),
            {"appointment_id": appt.id, "rating": 5, "comment": "Ajoyib!"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())

        notifs = Notification.objects.filter(
            user=self.doctor_user, type=Notification.Type.NEW_REVIEW
        )
        self.assertEqual(notifs.count(), 1)
        notif = notifs.first()
        self.assertIn("⭐", notif.body)
        self.assertEqual(notif.data["rating"], 5)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True
)
class CompleteAppointmentTriggersReviewNotificationTests(APITestCase):
    """Doctor `/complete/` chaqirsa patient'ga REVIEW_REMINDER notification yaratiladi."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Terapevt", icon="🩺")

        cls.doctor_user = User.objects.create_user(
            phone="+998901111111",
            full_name="Doctor Bek",
            role=User.Role.DOCTOR,
            active_role=User.Role.DOCTOR,
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )

        cls.patient = User.objects.create_user(
            phone="+998902222222",
            full_name="Patient Aziza",
            role=User.Role.PATIENT,
        )

    def test_complete_endpoint_creates_review_reminder_notification(self):
        from app.notifications.models import Notification

        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 4),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.APPROVED,
        )

        self.assertEqual(Notification.objects.filter(user=self.patient).count(), 0)

        self.client.force_authenticate(user=self.doctor_user)
        response = self.client.post(
            reverse("doctor-appointment-complete", kwargs={"pk": appt.id}),
            {"notes": "Bemor sog'lom"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())

        appt.refresh_from_db()
        self.assertEqual(appt.status, "completed")

        notifications = Notification.objects.filter(user=self.patient)
        self.assertEqual(notifications.count(), 1)

        notif = notifications.first()
        self.assertEqual(notif.type, Notification.Type.REVIEW_REMINDER)
        # Catalog `review_request` title (app/notifications/catalog.py)
        self.assertEqual(notif.title, "Sharhingiz kerak")
        self.assertIn("Doctor Bek", notif.body)
        # Task `data` ni int sifatida saqlaydi (JSONField), shuning uchun
        # ikkala tomonni str ga keltirib taqqoslaymiz (JSON type-agnostik).
        self.assertEqual(str(notif.data["appointment_id"]), str(appt.id))
        self.assertEqual(str(notif.data["doctor_id"]), str(self.doctor.id))

    def test_complete_pending_appointment_does_not_notify(self):
        """Pending appointmentni yakunlash 400 qaytaradi, notification yaratilmaydi."""
        from app.notifications.models import Notification

        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=date(2026, 5, 4),
            start_time=time(10, 0),
            end_time=time(10, 30),
            status=Appointment.Status.PENDING,
        )

        self.client.force_authenticate(user=self.doctor_user)
        response = self.client.post(
            reverse("doctor-appointment-complete", kwargs={"pk": appt.id}),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Notification.objects.filter(user=self.patient).count(), 0)
