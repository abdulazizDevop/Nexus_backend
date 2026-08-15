from datetime import date as date_cls, timedelta

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.doctors.models import DoctorPatient
from core.permissions import IsDoctor, IsVerifiedDoctor

from ..models import DailyCalorieLimit, Treatment, TreatmentLog
from ..serializers import (
    _validate_doctor_patient_link,
    DailyCalorieLimitSerializer,
    DailyCalorieLimitSetSerializer,
    DoctorTreatmentCreateSerializer,
    TreatmentLogSerializer,
    TreatmentMarkSerializer,
    TreatmentSerializer,
    TreatmentStatsSerializer,
)

User = get_user_model()

# Streak (ketma-ket kunlar) hisoblashda nechta kun orqaga qaralishi.
STREAK_LOOKBACK_DAYS = 365


def _today_logs_prefetch():
    """Bugungi loglarni `today_logs` attributiga prefetch qiladi (N+1 oldini olish)."""
    return models.Prefetch(
        "logs",
        queryset=TreatmentLog.objects.filter(date=timezone.localdate()),
        to_attr="today_logs",
    )


def _destroy_with_archived_logs(instance):
    """Treatment'ni o'chiradi, COMPLETED loglarni tarix uchun saqlaydi (SET_NULL)."""
    instance.logs.exclude(status=TreatmentLog.Status.COMPLETED).delete()
    instance.delete()


def compute_treatment_stats(user) -> dict:
    """Foydalanuvchi uchun oylik muolaja statistikasi (bemor + doctor ulashadi).

    Per-doza: bajarilgan slotlar / REJALASHTIRILGAN slotlar. Maxraj JADVALDAN
    (loglardan emas). O'chirilgan muolaja loglari (treatment=NULL arxiv) ham
    hisobga kiradi — off-schedule qatori sifatida (reja=bajarilgan), shu sabab
    tarix o'chirilgandan keyin ham completion/streak buzilmaydi.
    """
    today = timezone.localdate()
    first_day = today.replace(day=1)

    # Streak oynasi oy boshidan oldinroqqa cho'zilishi mumkin → kengroq diapazon.
    streak_start = min(first_day, today - timedelta(days=STREAK_LOOKBACK_DAYS))

    # Har (treatment, kun) uchun rejalashtirilgan slotlar — PRN'siz muolajalar.
    sched_td = {}  # (treatment_id, date) -> slots
    treatments = Treatment.objects.filter(user=user).exclude(is_as_needed=True)
    for t in treatments:
        spd = t.slots_per_day()
        if spd == 0:
            continue
        start = streak_start
        if t.created_at:
            # LOCAL sana — UTC .date() yarim tunda bir kun siljitib parity buzadi.
            created_local = timezone.localtime(t.created_at).date()
            if created_local > start:
                start = created_local
        end = today if not t.end_date else min(today, t.end_date)
        d = start
        while d <= end:
            if t._scheduled_on(d):
                sched_td[(t.id, d)] = spd
            d += timedelta(days=1)

    # Completed loglar — per (treatment, kun). O'chirilgan muolaja (treatment=NULL)
    # loglari ham kiradi — tarix saqlanadi.
    comp_td = {}
    completed_logs = (
        TreatmentLog.objects.filter(
            user=user,
            status=TreatmentLog.Status.COMPLETED,
            date__gte=streak_start,
            date__lte=today,
        )
        .filter(
            models.Q(treatment__is_as_needed=False)
            | models.Q(treatment__isnull=True)
        )
        .values("treatment_id", "date")
        .annotate(c=Count("id"))
    )
    for row in completed_logs:
        comp_td[(row["treatment_id"], row["date"])] = row["c"]

    # Per-kun yig'indilar (konsistent): jadvalda BOR kun completed slotga CAP;
    # jadvalda YO'Q, lekin bajarilgan (off-schedule) → maxraj = numerator (>100% imkonsiz).
    sched_per_day = {}
    completed_per_day = {}
    for key in set(sched_td) | set(comp_td):
        _tid, d = key
        sched = sched_td.get(key, 0)
        comp = comp_td.get(key, 0)
        if sched == 0 and comp > 0:
            sched = comp
        comp = min(comp, sched)
        sched_per_day[d] = sched_per_day.get(d, 0) + sched
        completed_per_day[d] = completed_per_day.get(d, 0) + comp

    denominator = sum(c for d, c in sched_per_day.items() if first_day <= d <= today)
    numerator = sum(c for d, c in completed_per_day.items() if first_day <= d <= today)

    rate = round((numerator / denominator) * 100) if denominator > 0 else 0
    missed = max(0, denominator - numerator)

    # Streak — bugundan orqaga: kunning HAMMA sloti bajarilsa sanaladi. BUGUN hali
    # to'liq bo'lmasa — neytral (kun tugamagan; ertalab streak 0 ko'rinib qolmasin).
    streak = 0
    check = today
    limit = today - timedelta(days=STREAK_LOOKBACK_DAYS)
    today_sched = sched_per_day.get(today, 0)
    today_done = today_sched > 0 and completed_per_day.get(today, 0) >= today_sched
    if today_sched > 0 and not today_done:
        check = today - timedelta(days=1)
    while check >= limit:
        sched = sched_per_day.get(check, 0)
        if sched == 0:
            check -= timedelta(days=1)
            continue
        if completed_per_day.get(check, 0) >= sched:
            streak += 1
            check -= timedelta(days=1)
        else:
            break

    return {
        "total": denominator,      # rejalashtirilgan slotlar (maxraj)
        "completed": numerator,     # bajarilgan slotlar (cap bilan)
        "skipped": missed,          # o'tkazib yuborilgan = rejalashtirilgan − bajarilgan
        "completion_rate": rate,
        "streak": streak,
    }


def _notify_patient_calorie(patient, cleared: bool):
    """Doctor kaloriya normasini belgilaganda/o'chirganda bemorga push (patient app)."""
    from app.notifications.models import DeviceToken, Notification
    from app.notifications.utils import notify

    if cleared:
        title = "Kaloriya normasi olib tashlandi"
        body = "Shifokoringiz kunlik kaloriya normangizni olib tashladi."
    else:
        title = "Kaloriya normasi yangilandi"
        body = "Shifokoringiz sizga kunlik kaloriya normasini belgiladi."
    try:
        notify(
            user=patient,
            type=Notification.Type.CALORIE_LIMIT,
            title=title,
            body=body,
            app_scope=DeviceToken.AppScope.PATIENT,
        )
    except Exception:
        pass  # push xatosi limit operatsiyasini buzmasin
