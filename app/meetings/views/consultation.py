"""Konsultatsiya (bir martalik pullik video-qabul) — patient-facing endpointlar.

Oqim: slots (bo'sh vaqt) → book (slot-lock + Payment) → to'lov (webhook confirm) →
call-token (belgilangan vaqtda LiveKit). Doctor sozlamasi doctors app'da
(DoctorProfileViewSet.me). Webhook confirm (_confirm_consultation) provider-agnostik.
"""
import logging
from datetime import date as date_cls, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.doctors.models import DoctorProfile, Slot
from app.users.models import User
from core.permissions import IsVerifiedDoctor, get_request_role
from services.livekit import build_identity, create_room, create_token, generate_room_name

from ..models import CONSULTATION_SLOT_GRACE_MIN, Consultation
from ..serializers import (
    ConsultationBookResponseSerializer,
    ConsultationBookSerializer,
    ConsultationSerializer,
    ConsultationSlotSerializer,
)

logger = logging.getLogger(__name__)

# Video-oyna: boshlanishdan 20 daq oldin ... tugashdan 10 daq keyin (grace).
# 20 daq — ikkala tomon oldindan ulanib kamera/mikrofon/aloqani tekshirsin.
CALL_EARLY_MIN = 20
CALL_GRACE_MIN = 10


@extend_schema(tags=["Konsultatsiya"])
class ConsultationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Bemor konsultatsiyalari: ro'yxat, booking, slotlar, video, bekor qilish."""

    serializer_class = ConsultationSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        # Doctor rejimi (o'z konsultatsiyalarini ko'rish / qo'ng'iroq) — tasdiqlangan
        # doctor only: boshqa doctor-operatsion endpointlar bilan bir xil gate
        # (tasdiqlanmagan doctor -> 403 doctor_not_verified). Bemor rejimi —
        # oddiy autentifikatsiya (booking/slot/cancel bemornики).
        if get_request_role(self.request) == User.Role.DOCTOR:
            return [IsVerifiedDoctor()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Consultation.objects.none()
        qs = Consultation.objects.select_related(
            "doctor__user", "doctor__specialty", "patient"
        ).order_by("-date", "-start_time")
        # Doctor scope -> o'ziga band qilinganlar; aks holda bemor o'ziniki.
        if get_request_role(self.request) == User.Role.DOCTOR:
            profile = getattr(self.request.user, "doctor_profile", None)
            return qs.filter(doctor=profile) if profile else qs.none()
        return qs.filter(patient=self.request.user)

    def _payment_url_for(self, consultation, provider_name=None):
        """Pending konsultatsiya uchun checkout URL. MAVJUD Payment'ni qayta ishlatadi
        (1 konsultatsiya = 1 order_id → webhook idempotent; retry'da dublikat payment
        yaratilmaydi).

        Payment yaratish + bog'lash consultation qatorini `select_for_update` bilan
        ATOMIC — parallel retry/double-tap bitta konsultatsiyaga IKKI Payment (ikki
        chargeable order → bemor double-charge) yaratmasin. Sekin provider chaqiruvi
        (create_payment, tarmoq) lock TASHQARISIDA. Payment tarmoqdan OLDIN commit
        bo'lgani uchun url-xato (502) bo'lsa ham provider bog'lanadi — /pay/ retry ishlaydi.
        """
        from app.payments.utils import build_consultation_payment
        from services.payments import get_provider

        with transaction.atomic():
            c = (
                Consultation.objects.select_for_update()
                .filter(pk=consultation.pk)
                .first()
            ) or consultation
            # Lock ichida qayta tekshiruv: caller check'idan keyin expire/cancel band
            # holatini o'zgartirган bo'lsa — EXPIRED/CANCELLED uchun to'lov URL bermaymiz.
            if c.status != Consultation.Status.PENDING_PAYMENT:
                raise ValueError(
                    f"Konsultatsiya {c.pk} PENDING_PAYMENT emas ({c.status})"
                )
            payment = c.payment
            if payment is None:
                if not provider_name:
                    # Payment hali yaratilmagan (booking'da DB xato) + provider yo'q —
                    # get_provider(None) crash o'rniga toza xato (caller 502 beradi).
                    raise ValueError("provider_name majburiy: payment hali yaratilmagan")
                # Provider'ni build'dan OLDIN validatsiya — yaroqsiz provider bilan
                # stuck (unpayable) Payment DB'ga yozilib qolmasin.
                get_provider(provider_name)
                payment = build_consultation_payment(c.patient, c, provider_name)
                c.payment = payment
                c.save(update_fields=["payment", "updated_at"])
        return get_provider(payment.provider).create_payment(payment)

    # ---- Booking (POST /consultations/) ----
    @extend_schema(
        request=ConsultationBookSerializer,
        responses=ConsultationBookResponseSerializer,
        summary="Konsultatsiya booking + to'lov havolasi",
    )
    def create(self, request):
        ser = ConsultationBookSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        provider_name = d["provider"]

        doctor = (
            DoctorProfile.objects.filter(
                id=d["doctor_id"], user__is_active=True, is_deleted=False
            )
            .select_related("user")
            .first()
        )
        if not doctor or not doctor.is_verified:
            return Response({"detail": "Shifokor topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        # Gate: yoqilgan + MODERATSIYADAN O'TGAN (approved) + narx > 0.
        if (
            not doctor.consultation_enabled
            or doctor.consultation_status != DoctorProfile.ConsultationStatus.APPROVED
            or not doctor.consultation_price
            or doctor.consultation_price <= 0
        ):
            return Response(
                {"detail": "Bu shifokor konsultatsiya qabul qilmaydi."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if d["date"] < timezone.localdate():
            return Response(
                {"detail": "O'tgan sanaga konsultatsiya belgilash mumkin emas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Bugungi kun uchun o'tgan vaqtli slotni bloklaymiz — slot boshlanib
        # grace (CONSULTATION_SLOT_GRACE_MIN) ham o'tsa. slots() bilan bir xil
        # qoida (slot ko'rinadi-yu POST 400 bo'lib qolmasin).
        now_local = timezone.localtime()
        if d["date"] == now_local.date():
            slot_dt = timezone.make_aware(
                datetime.combine(d["date"], d["time"]),
                timezone.get_current_timezone(),
            )
            if slot_dt + timedelta(minutes=CONSULTATION_SLOT_GRACE_MIN) <= now_local:
                return Response(
                    {"detail": "O'tgan vaqtga konsultatsiya belgilash mumkin emas."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        from services.payments import get_provider

        try:
            get_provider(provider_name)  # provider_name validatsiyasi (URL helperda)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Konsultatsiya: noto'g'ri provider %s (%s)", provider_name, exc)
            return Response({"detail": "Noto'g'ri to'lov provayderi."}, status=status.HTTP_400_BAD_REQUEST)

        # Atomic slot-lock: FREE → BOOKED + Consultation(pending_payment).
        with transaction.atomic():
            slot = (
                Slot.objects.select_for_update()
                .filter(doctor=doctor, date=d["date"], start_time=d["time"])
                .first()
            )
            if not slot:
                return Response(
                    {"detail": "Bu vaqt uchun slot mavjud emas."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if slot.status != Slot.Status.FREE:
                held = slot.consultation
                # Self-block fix: slot bemorning O'Z to'lanmagan bandi bilan band
                # bo'lsa — 409 emas, o'sha bandni qaytaramiz (Payme'dan to'lamay
                # qaytgan bemor xuddi shu slotni qayta to'lay olsin). 409 slot_taken
                # faqat BOSHQA bemor ushlab turganda.
                if not (
                    held
                    and held.patient_id == request.user.id
                    and held.status == Consultation.Status.PENDING_PAYMENT
                ):
                    return Response(
                        {"code": "slot_taken", "detail": "Bu slot allaqachon band."},
                        status=status.HTTP_409_CONFLICT,
                    )
                consultation = held
                created = False
            else:
                consultation = Consultation.objects.create(
                    patient=request.user,
                    doctor=doctor,
                    date=d["date"],
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    amount=doctor.consultation_price,
                    status=Consultation.Status.PENDING_PAYMENT,
                )
                slot.status = Slot.Status.BOOKED
                slot.consultation = consultation
                slot.save(update_fields=["status", "consultation", "updated_at"])
                created = True

        # To'lov havolasi (slot-lock tashqarisida) — mavjud Payment qayta ishlatiladi
        # (retry idempotent: yangi booking->yangi Payment, o'z bandini qayta->o'sha).
        try:
            payment_url = self._payment_url_for(consultation, provider_name)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Konsultatsiya booking: payment_url xato consultation=%s provider=%s",
                consultation.id, provider_name,
            )
            return Response(
                {"detail": "To'lov havolasini yaratib bo'lmadi. Keyinroq urinib ko'ring."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "booking_id": consultation.id,
                "status": consultation.status,
                "amount": consultation.amount,
                "payment_url": payment_url,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # ---- To'lovni qayta boshlash (POST /consultations/{id}/pay/) ----
    @extend_schema(
        request=None,
        responses=ConsultationBookResponseSerializer,
        summary="To'lovni qayta boshlash (pending konsultatsiya) — yangi payment_url",
        description=(
            "Bemor 'Mening konsultatsiyalarim' dan to'lanmagan bandni davom ettiradi. "
            "Mavjud Payment qayta ishlatiladi (order o'zgarmaydi, webhook idempotent) — "
            "faqat yangi checkout URL qaytariladi."
        ),
    )
    @action(detail=True, methods=["post"], url_path="pay")
    def pay(self, request, pk=None):
        consultation = self.get_object()  # queryset scope: bemor o'ziniki (404 begona)
        if consultation.patient_id != request.user.id:
            return Response({"detail": "Ruxsat yo'q."}, status=status.HTTP_403_FORBIDDEN)
        if consultation.status != Consultation.Status.PENDING_PAYMENT:
            return Response(
                {"detail": "Bu konsultatsiya uchun to'lov kutilmayapti."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Odatda payment mavjud (booking'da yaratilgan) → provider e'tiborsiz.
            # Faqat nodir holatda (payment None) body'dagi `provider` fallback bo'ladi.
            payment_url = self._payment_url_for(consultation, request.data.get("provider"))
        except Exception:  # noqa: BLE001
            logger.exception(
                "Konsultatsiya %s: to'lovni qayta boshlash xato", consultation.id
            )
            return Response(
                {"detail": "To'lov havolasini yaratib bo'lmadi. Keyinroq urinib ko'ring."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "booking_id": consultation.id,
                "status": consultation.status,
                "amount": consultation.amount,
                "payment_url": payment_url,
            },
            status=status.HTTP_200_OK,
        )

    # ---- Bo'sh slotlar (GET /consultations/slots/?doctor_id=&date=) ----
    @extend_schema(
        responses=ConsultationSlotSerializer(many=True),
        summary="Doctor konsultatsiya slotlari (band ham) — {time, available}",
    )
    @action(detail=False, methods=["get"], url_path="slots")
    def slots(self, request):
        doctor_id = request.query_params.get("doctor_id")
        date_str = request.query_params.get("date")
        if not doctor_id or not doctor_id.isdigit() or not date_str:
            return Response(
                {"detail": "doctor_id (raqam) va date (YYYY-MM-DD) majburiy."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            target = date_cls.fromisoformat(date_str)
        except ValueError:
            return Response({"detail": "date YYYY-MM-DD bo'lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        doctor = DoctorProfile.objects.filter(id=doctor_id).first()
        # O'chiq / moderatsiyadan o'tmagan / doctor yo'q → bo'sh ro'yxat (mobil tabni yashiradi).
        if (
            not doctor
            or not doctor.consultation_enabled
            or doctor.consultation_status != DoctorProfile.ConsultationStatus.APPROVED
        ):
            return Response([])

        now = timezone.localtime()
        is_today = target == now.date()
        tz = timezone.get_current_timezone()
        grace = timedelta(minutes=CONSULTATION_SLOT_GRACE_MIN)
        out = []
        for s in Slot.objects.filter(doctor=doctor, date=target).order_by("start_time"):
            # Slot boshlangach grace (10 daq) davomida hali "available" — bemor
            # ozgina kechiksa ham band qila olsin (14:00 slot 14:10 gacha ochiq).
            slot_dt = timezone.make_aware(datetime.combine(target, s.start_time), tz)
            available = s.status == Slot.Status.FREE and (
                not is_today or slot_dt + grace > now
            )
            out.append({"time": s.start_time.strftime("%H:%M"), "available": available})
        return Response(out)

    # ---- Video token (POST /consultations/{id}/call-token/) — ikkala tomon ----
    @extend_schema(summary="LiveKit token (belgilangan vaqt oynasida, ikkala tomon)")
    @action(detail=True, methods=["post"], url_path="call-token")
    def call_token(self, request, pk=None):
        consultation = (
            Consultation.objects.select_related("doctor__user", "patient")
            .filter(id=pk)
            .first()
        )
        if not consultation:
            return Response({"detail": "Konsultatsiya topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        if user.id == consultation.patient_id:
            scope, name = "patient", (user.full_name or "Bemor")
        elif user.id == consultation.doctor.user_id:
            scope, name = "doctor", (user.full_name or "Shifokor")
        else:
            return Response({"detail": "Ruxsat yo'q."}, status=status.HTTP_403_FORBIDDEN)

        if consultation.status != Consultation.Status.CONFIRMED:
            return Response(
                {"detail": "Konsultatsiya tasdiqlanmagan (to'lov yakunlanmagan)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Vaqt-oyna: start − 5min … end + 10min.
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(
            datetime.combine(consultation.date, consultation.start_time), tz
        )
        end_dt = timezone.make_aware(
            datetime.combine(consultation.date, consultation.end_time), tz
        )
        now = timezone.now()
        if now < start_dt - timedelta(minutes=CALL_EARLY_MIN):
            return Response(
                {"code": "too_early", "detail": "Konsultatsiya vaqti hali kelmadi."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if now > end_dt + timedelta(minutes=CALL_GRACE_MIN):
            return Response(
                {"code": "window_closed", "detail": "Konsultatsiya vaqti tugadi."},
                status=status.HTTP_403_FORBIDDEN,
            )

        room = consultation.room_name or generate_room_name()
        if not consultation.room_name:
            consultation.room_name = room
            consultation.save(update_fields=["room_name", "updated_at"])
        try:
            create_room(room)
        except Exception:  # noqa: BLE001
            logger.warning("Konsultatsiya %s: LiveKit room yaratish xato (davom)", consultation.id)
        token = create_token(
            room_name=room,
            participant_name=name,
            participant_identity=build_identity(user.id, scope),
        )
        return Response(
            {"room_name": room, "token": token, "livekit_url": settings.LIVEKIT_URL}
        )

    # ---- Bekor qilish (POST /consultations/{id}/cancel/) — bemor ----
    @extend_schema(
        responses=ConsultationSerializer,
        summary="Konsultatsiyani bekor qilish (bemor). Refund MVP'da yo'q.",
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        obj = self.get_object()  # patient-scoped (egalik + 404)
        # TOCTOU-safe: konsultatsiyani QULFLAB status'ni lock ichida re-check
        # (parallel webhook confirm bilan poygani serializatsiya qiladi).
        with transaction.atomic():
            consultation = (
                Consultation.objects.select_for_update().filter(id=obj.id).first()
            )
            if consultation.status not in (
                Consultation.Status.PENDING_PAYMENT,
                Consultation.Status.CONFIRMED,
            ):
                return Response(
                    {"detail": "Bu konsultatsiyani bekor qilib bo'lmaydi."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Kim bekor qildi — rolga qarab (endpoint bemor + shifokorga ochiq).
            was_paid = consultation.status == Consultation.Status.CONFIRMED
            role_is_doctor = get_request_role(request) == User.Role.DOCTOR
            consultation.status = (
                Consultation.Status.CANCELLED_BY_DOCTOR
                if role_is_doctor
                else Consultation.Status.CANCELLED_BY_PATIENT
            )
            consultation.cancelled_by = "doctor" if role_is_doctor else "patient"
            consultation.save(update_fields=["status", "cancelled_by", "updated_at"])
            slot = (
                Slot.objects.select_for_update()
                .filter(consultation=consultation)
                .first()
            )
            if slot:
                slot.status = Slot.Status.FREE
                slot.consultation = None
                slot.save(update_fields=["status", "consultation", "updated_at"])
        # Confirmed (to'langan) konsultatsiya bekor qilindi — bemorga pul qaytishi kerak.
        # Auto-refund hali yo'q (Payme sandbox kutilmoqda) → admin qo'lda refund qilsin
        # (alert). Shifokor bekor qilishi kam emas — bu holat ko'rinadigan bo'lsin.
        if was_paid:
            from app.payments.views.webhook import _alert_admins_money_issue

            _alert_admins_money_issue(
                "Konsultatsiya bekor qilindi — bemorga REFUND kerak",
                f"Consultation #{consultation.id} · {consultation.amount} so'm\n"
                f"Bekor qildi: {'shifokor' if role_is_doctor else 'bemor'} "
                f"(patient user={consultation.patient_id})\n"
                f"To'langan konsultatsiya bekor — qo'lda REFUND kerak (auto-refund hali yo'q).",
            )
        return Response(ConsultationSerializer(consultation).data)
