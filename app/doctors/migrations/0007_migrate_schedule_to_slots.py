"""Eski DoctorSchedule + BlockedSlot ma'lumotlarini yangi Slot jadvaliga ko'chirish.

Spec §10 step 2: Mavjud DoctorSchedule + BlockedSlot'larni keyingi 60-90 kun uchun
aniq slot'larga konvertatsiya.

Step 3: Mavjud Appointment'larni slot bilan bog'lash.

Production deploy uchun majburiy. Dev SQLite'da odatda ma'lumot bo'lmaydi —
RunPython migratsiyasi bo'sh result bilan o'tib ketadi.
"""

from datetime import datetime, timedelta

from django.db import IntegrityError, migrations, transaction
from django.utils import timezone


SLOT_WINDOW_DAYS = 90


def _generate_times(start_t, end_t, slot_minutes):
    """[start..end) oralig'ida slot_minutes davriy time juftliklar."""
    if not slot_minutes or slot_minutes <= 0:
        return []
    base_date = datetime(2000, 1, 1).date()
    cursor = datetime.combine(base_date, start_t.replace(second=0, microsecond=0))
    end_dt = datetime.combine(base_date, end_t.replace(second=0, microsecond=0))
    duration = timedelta(minutes=slot_minutes)
    out = []
    while cursor + duration <= end_dt:
        out.append((cursor.time(), (cursor + duration).time()))
        cursor += duration
    return out


def forwards(apps, schema_editor):
    DoctorSchedule = apps.get_model("doctors", "DoctorSchedule")
    BlockedSlot = apps.get_model("doctors", "BlockedSlot")
    Slot = apps.get_model("doctors", "Slot")
    Appointment = apps.get_model("meetings", "Appointment")

    schedules = DoctorSchedule.objects.filter(is_active=True)
    if not schedules.exists():
        return

    # Asia/Tashkent localdate — UTC va Tashkent yarim tunida farq bo'lmasligi uchun
    today = timezone.localdate()
    horizon = today + timedelta(days=SLOT_WINDOW_DAYS)

    # 1) Schedule + BlockedSlot → Slot lar
    for sched in schedules:
        # Doctor uchun ushbu sanalar oralig'idagi blocked slotlarni oldindan oling
        blocked_qs = BlockedSlot.objects.filter(
            doctor=sched.doctor,
            date__gte=today,
            date__lte=horizon,
        )
        blocked_by_date = {}
        for b in blocked_qs:
            blocked_by_date.setdefault(b.date, []).append(
                (b.start_time, b.end_time, b.reason or "Yopilgan")
            )

        cursor_date = today
        while cursor_date <= horizon:
            if cursor_date.weekday() == sched.weekday:
                # Generate slots for this date
                for start_t, end_t in _generate_times(
                    sched.start_time, sched.end_time, sched.slot_duration
                ):
                    # Blocked oraliqlar bilan kesishuvni tekshir
                    is_blocked = False
                    block_reason = ""
                    for b_start, b_end, reason in blocked_by_date.get(cursor_date, []):
                        if b_start <= start_t < b_end:
                            is_blocked = True
                            block_reason = reason
                            break

                    Slot.objects.update_or_create(
                        doctor=sched.doctor,
                        date=cursor_date,
                        start_time=start_t,
                        defaults={
                            "end_time": end_t,
                            "status": "blocked" if is_blocked else "free",
                            "reason": block_reason if is_blocked else "",
                        },
                    )
            cursor_date += timedelta(days=1)

    # 2) Mavjud appointment'larni mos slotga bog'lash (status=approved/pending bo'lsa)
    # Eski sxemada Appointment'da unique constraint yo'q edi — overlap appointmentlar
    # bo'lishi mumkin. Slot.appointment OneToOneField bo'lgani uchun, har slot faqat
    # bitta appointment bilan bog'lanadi. Konflikt bo'lsa eng so'nggisini saqlaymiz.
    active_appointments = Appointment.objects.filter(
        status__in=["pending", "approved"], date__gte=today
    ).order_by("date", "start_time", "-created_at")

    seen_keys = set()  # (doctor_id, date, start_time) — bitta slotga bir bog'lanish
    for appt in active_appointments:
        key = (appt.doctor_id, appt.date, appt.start_time)
        if key in seen_keys:
            # Overlap appointment — slotga bog'lamaymiz, lekin appointment qoladi
            continue
        seen_keys.add(key)

        slot = Slot.objects.filter(
            doctor=appt.doctor,
            date=appt.date,
            start_time=appt.start_time,
        ).first()
        try:
            with transaction.atomic():
                if slot:
                    slot.status = "booked"
                    slot.appointment = appt
                    slot.end_time = appt.end_time
                    slot.reason = ""
                    slot.save(
                        update_fields=[
                            "status",
                            "appointment",
                            "end_time",
                            "reason",
                            "updated_at",
                        ]
                    )
                else:
                    # Schedule'ga mos kelmaydigan appointment — yangi slot yaratamiz
                    Slot.objects.create(
                        doctor=appt.doctor,
                        date=appt.date,
                        start_time=appt.start_time,
                        end_time=appt.end_time,
                        status="booked",
                        appointment=appt,
                    )
        except IntegrityError:
            # Boshqa appointment shu slotga allaqachon bog'langan — skip
            continue


def reverse(apps, schema_editor):
    """Slotlar yana DoctorSchedule + BlockedSlot ga ajratilmaydi.

    Reverse migratsiya destruktiv emas — Slot jadvali keyingi migration
    (0008) tomonidan to'liq saqlanadi va eski jadvallar qaytadan tiklanadi
    (lekin bo'sh holda).
    """
    return


class Migration(migrations.Migration):

    dependencies = [
        ("doctors", "0006_create_slot"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
