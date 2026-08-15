from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + konstantalar
from .common import _avatar_url,_disp


class UserAdminSerializer(serializers.ModelSerializer):
    is_root = serializers.BooleanField(source="is_root_admin", read_only=True)
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "role",
            "active_role",
            "sex",
            "birth_date",
            "avatar",
            "admin_type",
            "referral_code",
            "telegram_chat_id",
            "is_active",
            "is_staff",
            "is_root",
            "date_joined",
        ]
        # XAVFSIZLIK: rol/tip generic PATCH orqali o'zgartirilmaydi (privilege
        # escalation — simple admin o'zini super qila olmasin). Rol o'zgartirish
        # FAQAT root-only change_role/promote_super/demote_super action'lari orqali.
        read_only_fields = [
            "id",
            "phone",
            "telegram_chat_id",
            "date_joined",
            "is_root",
            "role",
            "active_role",
            "admin_type",
            "is_staff",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _avatar_url(obj.avatar)


class UserAdminDetailSerializer(UserAdminSerializer):
    """Admin profil oynasi uchun kengaytirilgan serializer.

    Patient bo'lsa: connected doctorlar + appointmentlar + health indicators
    Doctor bo'lsa: connected patientlar + appointmentlar
    """

    connected_doctors = serializers.SerializerMethodField()
    connected_patients = serializers.SerializerMethodField()
    appointments = serializers.SerializerMethodField()
    health_indicators = serializers.SerializerMethodField()
    last_checkup = serializers.SerializerMethodField()
    doctor_profile = serializers.SerializerMethodField()
    doctor_payout_cards = serializers.SerializerMethodField()
    doctor_balance = serializers.SerializerMethodField()

    class Meta(UserAdminSerializer.Meta):
        fields = UserAdminSerializer.Meta.fields + [
            "connected_doctors",
            "connected_patients",
            "appointments",
            "health_indicators",
            "last_checkup",
            "doctor_profile",
            "doctor_payout_cards",
            "doctor_balance",
        ]

    @staticmethod
    def _doctor_profile(obj):
        """User'ning DoctorProfile'i (yo'q bo'lsa None) — takroriy getattr o'rniga."""
        return getattr(obj, "doctor_profile", None)

    def get_connected_doctors(self, obj):
        # Yandex Taxi identity: har user'da Patient profil bo'lishi mumkin.
        # Role'dan qat'i nazar, agar bog'langan doctor'lari bo'lsa, ko'rsatamiz.
        from app.doctors.models import DoctorPatient

        qs = DoctorPatient.objects.filter(patient=obj).select_related(
            "doctor__user", "doctor__specialty"
        )
        return [
            {
                "id": dp.doctor.user.id,
                "doctor_profile_id": dp.doctor.id,
                "full_name": dp.doctor.user.full_name,
                "phone": dp.doctor.user.phone,
                "specialty": (
                    pick_for(self.context, dp.doctor.specialty.name)
                    if dp.doctor.specialty else None
                ),
                "is_verified": dp.doctor.is_verified,
                "added_by": dp.added_by,
                "connected_at": dp.created_at.isoformat(),
            }
            for dp in qs
        ]

    def get_connected_patients(self, obj):
        # Agar DoctorProfile bor bo'lsa, ulagan patient'larni ko'rsatamiz —
        # admin/patient role bo'lsa ham (multi-role identity).
        from app.doctors.models import DoctorPatient

        profile = self._doctor_profile(obj)
        if not profile:
            return []
        qs = DoctorPatient.objects.filter(doctor=profile).select_related("patient")
        return [
            {
                "id": dp.patient.id,
                "full_name": dp.patient.full_name,
                "phone": dp.patient.phone,
                "sex": dp.patient.sex,
                "birth_date": dp.patient.birth_date.isoformat()
                if dp.patient.birth_date
                else None,
                "added_by": dp.added_by,
                "connected_at": dp.created_at.isoformat(),
            }
            for dp in qs
        ]

    def get_appointments(self, obj):
        # Multi-role: user ham patient ham doctor sifatida appointmentlarga
        # ega bo'lishi mumkin. Hammasini birlashtirib qaytaramiz.
        from app.meetings.models import Appointment

        patient_qs = Appointment.objects.filter(patient=obj).select_related(
            "doctor__user", "patient"
        )
        profile = self._doctor_profile(obj)
        doctor_qs = (
            Appointment.objects.filter(doctor=profile).select_related(
                "patient", "doctor__user"
            )
            if profile
            else Appointment.objects.none()
        )
        # Birlashtirib eng oxirgi 30 ta
        qs = list(patient_qs) + list(doctor_qs)
        qs.sort(key=lambda a: (a.date, a.start_time), reverse=True)
        qs = qs[:30]
        return [
            {
                "id": a.id,
                "date": a.date.isoformat(),
                "start_time": a.start_time.strftime("%H:%M"),
                "end_time": a.end_time.strftime("%H:%M"),
                "meeting_type": a.meeting_type,
                "status": a.status,
                "status_display": a.get_status_display(),
                "patient_name": a.patient.full_name if a.patient else None,
                "doctor_name": a.doctor.user.full_name if a.doctor else None,
                "reason": a.reason,
            }
            for a in qs
        ]

    def get_health_indicators(self, obj):
        # Multi-role: har user'da HealthIndicator bo'lishi mumkin (manual
        # yoki diet_ai). Role'dan qat'i nazar yozuvlar bo'lsa qaytaramiz.
        from app.health_packages.models import HealthIndicator

        # Har indicator_type uchun eng oxirgi yozuv (ordering=-date)
        seen = {}
        for ind in (
            HealthIndicator.objects.filter(user=obj)
            .select_related("indicator_type")
            .order_by("-date")
        ):
            if ind.indicator_type_id not in seen:
                seen[ind.indicator_type_id] = ind
        return [
            {
                "name": pick_for(self.context, ind.indicator_type.name),
                "value": ind.display_value,
                "unit": ind.indicator_type.unit,
                "icon": ind.indicator_type.icon,
                "date": ind.date.isoformat(),
            }
            for ind in seen.values()
        ]

    def get_last_checkup(self, obj):
        # Multi-role: kunlik kayfiyat har user'da bo'lishi mumkin.
        from app.health_packages.models import DailySituationCheckup

        checkup = DailySituationCheckup.objects.filter(user=obj).first()
        if not checkup:
            return None
        return {
            "status": checkup.status,
            "status_display": checkup.get_status_display(),
            "note": checkup.note,
            "date": checkup.date.isoformat(),
        }

    def get_doctor_profile(self, obj):
        """DoctorProfile + certificates — agar user'da bor bo'lsa."""
        profile = self._doctor_profile(obj)
        if not profile:
            return None

        certificates = [
            {
                "id": c.id,
                "title": c.title,
                "image_url": _avatar_url(c.image),
                "issuer": c.issuer,
                "year": c.year,
            }
            for c in profile.certificates.all().order_by("-year")
        ]
        return {
            "id": profile.id,
            "specialty": (
                pick_for(self.context, profile.specialty.name)
                if profile.specialty else None
            ),
            "experience_years": profile.experience_years,
            "bio": profile.bio,
            "is_verified": profile.is_verified,
            "commission_percent": profile.commission_percent,
            "total_patients": profile.connected_patients_count
            if hasattr(profile, "connected_patients_count")
            else None,
            "certificates": certificates,
        }

    def get_doctor_payout_cards(self, obj):
        """Doctor pul yechish kartalari — agar DoctorProfile bo'lsa."""
        profile = self._doctor_profile(obj)
        if not profile:
            return None
        from app.payments.models import DoctorPayoutCard

        cards = DoctorPayoutCard.objects.filter(doctor=profile)
        return [
            {
                "id": c.id,
                "card_type": c.card_type,
                "card_last4": c.card_number[-4:] if c.card_number else "",
                "card_holder": c.card_holder,
                "bank_name": c.bank_name,
                "is_primary": c.is_primary,
                "atmos_asl_card_id": c.atmos_asl_card_id,
                "atmos_asl_processing_type": c.atmos_asl_processing_type,
                "created_at": c.created_at.isoformat(),
            }
            for c in cards
        ]

    def get_doctor_balance(self, obj):
        """Doctor balansi — agar DoctorProfile bo'lsa."""
        profile = self._doctor_profile(obj)
        if not profile:
            return None
        from app.payments.models import DoctorBalance

        balance = DoctorBalance.objects.filter(doctor=profile).first()
        if not balance:
            return {
                "balance": "0.00",
                "total_earned": "0.00",
                "total_withdrawn": "0.00",
                "held_amount": "0.00",
            }
        return {
            "balance": str(balance.balance),
            "total_earned": str(balance.total_earned),
            "total_withdrawn": str(balance.total_withdrawn),
            "held_amount": str(balance.held_amount),
        }


