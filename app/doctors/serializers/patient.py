from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin
from .common import _TariffMixin,_media_url


class AddByPhoneSerializer(serializers.Serializer):
    """Telefon orqali doctor/patient qo'shish"""

    phone = serializers.CharField(max_length=15)

    def validate_phone(self, value):
        if not User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                "Bu telefon raqamli foydalanuvchi topilmadi."
            )
        return value


class DoctorPatientSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_phone = serializers.CharField(source="patient.phone", read_only=True)
    doctor_phone = serializers.CharField(source="doctor.user.phone", read_only=True)
    patient_profile_id = serializers.IntegerField(read_only=True)
    patient_avatar = serializers.SerializerMethodField()
    doctor_avatar = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_patient_avatar(self, obj):
        return _media_url(obj.patient.avatar)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_doctor_avatar(self, obj):
        return _media_url(obj.doctor.user.avatar)

    class Meta:
        model = DoctorPatient
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "doctor_phone",
            "doctor_avatar",
            "patient",
            "patient_profile_id",
            "patient_name",
            "patient_phone",
            "patient_avatar",
            "added_by",
            "created_at",
        ]
        read_only_fields = fields


class PatientWithHealthSerializer(_TariffMixin, serializers.ModelSerializer):
    """Bemor + oxirgi salomatlik ko'rsatkichlari (doctor uchun)"""

    avatar = serializers.SerializerMethodField()
    health_indicators = serializers.SerializerMethodField()
    last_checkup = serializers.SerializerMethodField()
    tariff_status = serializers.SerializerMethodField()
    tariff_days_left = serializers.SerializerMethodField()
    tariff_expires_at = serializers.SerializerMethodField()
    tariff_name = serializers.SerializerMethodField()
    last_chat_at = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    ai_report = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "sex",
            "birth_date",
            "avatar",
            "health_indicators",
            "last_checkup",
            "tariff_status",
            "tariff_days_left",
            "tariff_expires_at",
            "tariff_name",
            "last_chat_at",
            "unread_count",
            "ai_report",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _media_url(obj.avatar)

    def get_ai_report(self, obj):
        """Bemorning eng oxirgi AI insight hisoboti (severity + qisqa xulosa + sana)."""
        prefetched = self.context.get("report_by_patient")
        if prefetched is not None:
            rep = prefetched.get(obj.id)
        else:
            doctor = self.context.get("doctor_profile")
            if not doctor:
                return None
            from app.health_ai.models import AIHealthReport

            rep = AIHealthReport.objects.filter(doctor=doctor, patient=obj).first()
        if not rep:
            return None
        return {
            "id": rep.id,
            "severity": rep.severity,
            "summary": rep.summary,
            "period_start": rep.period_start.isoformat(),
            "seen_at": rep.seen_at.isoformat() if rep.seen_at else None,
        }

    def get_health_indicators(self, obj):
        """Har indicator type bo'yicha oxirgi qiymat. Postgres `distinct("field")`
        ishlatadi, SQLite (dev) uchun Python-side dedupe fallback.
        """
        prefetched = self.context.get("indicators_by_user")
        if prefetched is not None:
            indicators = prefetched.get(obj.id, [])
        else:
            from app.health_packages.models import HealthIndicator

            latest = (
                HealthIndicator.objects.filter(user=obj)
                .select_related("indicator_type")
                .order_by("indicator_type_id", "-date")
                .distinct("indicator_type_id")
            )

            try:
                indicators = list(latest)
            except Exception:
                # SQLite distinct(field) qo'llab-quvvatlamaydi
                seen = {}
                for ind in (
                    HealthIndicator.objects.filter(user=obj)
                    .select_related("indicator_type")
                    .order_by("-date")
                ):
                    if ind.indicator_type_id not in seen:
                        seen[ind.indicator_type_id] = ind
                indicators = list(seen.values())

        return [
            {
                "name": pick_for(self.context, ind.indicator_type.name),
                "value": ind.display_value,
                "unit": ind.indicator_type.unit,
                "icon": ind.indicator_type.icon,
                "date": ind.date.isoformat(),
            }
            for ind in indicators
        ]

    def get_last_checkup(self, obj):
        """Oxirgi kayfiyat tekshiruvi"""
        prefetched = self.context.get("checkup_by_user")
        if prefetched is not None:
            checkup = prefetched.get(obj.id)
        else:
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

    def _purchase(self, obj):
        return (self.context.get("purchase_by_patient") or {}).get(obj.id)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_chat_at(self, obj):
        return getattr(obj, "_last_chat_at", None)

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        return getattr(obj, "_unread_count", 0) or 0


class PatientDetailSerializer(PatientWithHealthSerializer):
    """Bemor to'liq ma'lumoti (doctor uchun) — muolajalar + qabullar tarixi"""

    treatments = serializers.SerializerMethodField()
    appointments = serializers.SerializerMethodField()

    class Meta(PatientWithHealthSerializer.Meta):
        fields = PatientWithHealthSerializer.Meta.fields + [
            "treatments",
            "appointments",
        ]

    def get_treatments(self, obj):
        """Bemorning faol muolajalari"""
        from app.treatment.models import Treatment

        treatments = (
            Treatment.objects.filter(user=obj, status=Treatment.Status.ACTIVE)
            .select_related("created_by")
            .order_by("time")
        )

        return [
            {
                "id": t.id,
                "title": t.title,
                "type": t.type,
                "type_display": t.get_type_display(),
                "dosage": t.dosage,
                "time": t.time.strftime("%H:%M") if t.time else None,
                "repeat": t.repeat,
                "end_date": t.end_date.isoformat() if t.end_date else None,
                "created_by": t.created_by.full_name if t.created_by else None,
                "scheduled_today": t.is_scheduled_today(),
            }
            for t in treatments
        ]

    def get_appointments(self, obj):
        """Bemor va doctorning qabullar tarixi (so'nggi 20 ta)"""
        from app.meetings.models import Appointment

        doctor_profile = self.context.get("doctor_profile")
        qs = Appointment.objects.filter(patient=obj)
        if doctor_profile:
            qs = qs.filter(doctor=doctor_profile)

        return [
            {
                "id": a.id,
                "date": a.date.isoformat(),
                "start_time": a.start_time.strftime("%H:%M"),
                "end_time": a.end_time.strftime("%H:%M"),
                "meeting_type": a.meeting_type,
                "status": a.status,
                "status_display": a.get_status_display(),
                "reason": a.reason,
                "notes": a.notes,
            }
            for a in qs.order_by("-date", "-start_time")[:20]
        ]
