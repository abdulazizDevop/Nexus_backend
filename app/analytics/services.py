"""Foydalanish analitikasi — mavjud domen yozuvlaridan hisoblash (Phase 1).

Har funksiya feature registry bo'ylab yuradi va TruncDate/ExtractHour/Count bilan
agregatsiya qiladi. Hech qanday yangi jadval kerak emas — butun tarixiy data'da
ishlaydi. Og'ir bo'lsa view darajasida cache qilinadi.
"""
import importlib
import logging
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate
from django.utils import timezone

from .registry import CATEGORIES, FEATURES, FEATURES_BY_KEY

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}


def _model(feature):
    module, cls = feature.model.rsplit(".", 1)
    return getattr(importlib.import_module(module), cls)


def period_start(period):
    """`period` (7d/30d/90d/365d/all) → boshlanish datetime yoki None (all)."""
    if not period or period == "all":
        return None
    return timezone.now() - timedelta(days=_PERIOD_DAYS.get(period, 30))


def _qs(feature, start=None):
    qs = _model(feature).objects.all()
    if feature.extra_filter:
        qs = qs.filter(**feature.extra_filter)
    if start is not None:
        qs = qs.filter(**{f"{feature.ts_field}__gte": start})
    return qs


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        logger.exception("analytics.%s", getattr(fn, "__name__", "?"))
        return default


# ── Umumiy (aggregate) ──────────────────────────────────────────────────

def feature_counts(period=None):
    """Har feature: jami count + noyob userlar soni. Ko'pdan kamga saralangan."""
    start = period_start(period)
    out = []
    for f in FEATURES:
        try:
            qs = _qs(f, start)
            out.append({
                "key": f.key,
                "label": f.label,
                "category": f.category,
                "count": qs.count(),
                "users": qs.values(f.user_field).distinct().count(),
            })
        except Exception:
            logger.exception("feature_counts %s", f.key)
            out.append({"key": f.key, "label": f.label, "category": f.category,
                        "count": 0, "users": 0})
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def category_counts(period=None):
    """Kategoriya bo'yicha: jami harakatlar + NOYOB userlar (distinct set).

    `users` — per-feature userlarni QO'SHMAYDI (bir user bir kategoriyada bir necha
    feature ishlatishi mumkin); haqiqiy distinct-user to'plami olinadi.
    """
    start = period_start(period)
    ev = defaultdict(int)
    user_sets = defaultdict(set)
    for f in FEATURES:
        try:
            qs = _qs(f, start)
            ev[f.category] += qs.count()
            for uid in qs.values_list(f.user_field, flat=True).distinct():
                if uid:
                    user_sets[f.category].add(uid)
        except Exception:
            logger.exception("category_counts %s", f.key)
    return [
        {
            "category": c,
            "label": CATEGORIES.get(c, c),
            "count": ev.get(c, 0),
            "users": len(user_sets.get(c, set())),
        }
        for c in CATEGORIES
        if ev.get(c) or user_sets.get(c)
    ]


def active_users(period=None):
    """Davr ichida kamida bitta faollik ko'rsatgan noyob userlar soni."""
    start = period_start(period)
    seen = set()
    for f in FEATURES:
        try:
            for uid in _qs(f, start).values_list(f.user_field, flat=True).distinct():
                if uid:
                    seen.add(uid)
        except Exception:
            logger.exception("active_users %s", f.key)
    return len(seen)


def hour_weekday_heatmap(period=None):
    """(hafta-kuni × soat) → count. Faqat datetime-ts feature'lar soatga hissa qo'shadi.

    weekday: Django ExtractWeekDay → 1=Yakshanba .. 7=Shanba.
    """
    start = period_start(period)
    grid = defaultdict(int)
    for f in FEATURES:
        if not f.has_time:
            continue
        try:
            rows = (
                _qs(f, start)
                .annotate(wd=ExtractWeekDay(f.ts_field), hr=ExtractHour(f.ts_field))
                .values("wd", "hr")
                .annotate(c=Count("id"))
            )
            for r in rows:
                if r["wd"] is not None and r["hr"] is not None:
                    grid[(r["wd"], r["hr"])] += r["c"]
        except Exception:
            logger.exception("heatmap %s", f.key)
    return [
        {"weekday": wd, "hour": hr, "count": c}
        for (wd, hr), c in sorted(grid.items())
    ]


def top_users(period=None, limit=20):
    """Eng faol userlar — barcha feature bo'yicha jami faollik."""
    start = period_start(period)
    counter = Counter()
    per_user_features = defaultdict(set)
    for f in FEATURES:
        try:
            for r in _qs(f, start).values(f.user_field).annotate(c=Count("id")):
                uid = r[f.user_field]
                if uid:
                    counter[uid] += r["c"]
                    per_user_features[uid].add(f.category)
        except Exception:
            logger.exception("top_users %s", f.key)

    top = counter.most_common(limit)
    User = get_user_model()
    users = {u.id: u for u in User.objects.filter(id__in=[uid for uid, _ in top])}
    result = []
    for uid, total in top:
        u = users.get(uid)
        cats = per_user_features.get(uid, set())
        result.append({
            "user_id": uid,
            "name": (u.full_name or u.phone) if u else str(uid),
            "phone": u.phone if u else None,
            "role": u.role if u else None,
            "total": total,
            # dominant kategoriya → "nima maqsadda" (segment)
            "segment": _dominant_segment(uid, start),
            "categories": sorted(cats),
        })
    return result


def _dominant_segment(user_id, start):
    """User eng ko'p qaysi KATEGORIYAda faol — 'nima maqsadda' segmenti."""
    cat_count = Counter()
    for f in FEATURES:
        try:
            n = _qs(f, start).filter(**{f.user_field: user_id}).count()
            if n:
                cat_count[f.category] += n
        except Exception:
            pass
    if not cat_count:
        return None
    return CATEGORIES.get(cat_count.most_common(1)[0][0])


def overview(period=None):
    """Dashboard uchun yagona chaqiruv — barcha aggregate bo'limlar."""
    return {
        "period": period or "all",
        "active_users": _safe(lambda: active_users(period), 0),
        "features": _safe(lambda: feature_counts(period), []),
        "categories": _safe(lambda: category_counts(period), []),
        "heatmap": _safe(lambda: hour_weekday_heatmap(period), []),
        "top_users": _safe(lambda: top_users(period), []),
    }


# ── Timeseries ──────────────────────────────────────────────────────────

def timeseries(feature_key, period=None):
    """Bitta feature — kunlik count (grafik uchun)."""
    f = FEATURES_BY_KEY.get(feature_key)
    if not f:
        return {"feature": feature_key, "results": []}
    start = period_start(period)
    rows = (
        _qs(f, start)
        .annotate(d=TruncDate(f.ts_field))
        .values("d")
        .annotate(c=Count("id"))
        .order_by("d")
    )
    return {
        "feature": feature_key,
        "label": f.label,
        "results": [
            {"date": r["d"].isoformat(), "count": r["c"]} for r in rows if r["d"]
        ],
    }


# ── Per-user ────────────────────────────────────────────────────────────

def user_usage(user_id, period=None):
    """Bitta user — har feature bo'yicha count + kunlik timeline + segment."""
    start = period_start(period)
    per_feature = []
    daily = defaultdict(int)
    for f in FEATURES:
        try:
            uqs = _qs(f, start).filter(**{f.user_field: user_id})
            cnt = uqs.count()
            if cnt:
                per_feature.append({
                    "key": f.key, "label": f.label,
                    "category": f.category, "count": cnt,
                })
            for r in uqs.annotate(d=TruncDate(f.ts_field)).values("d").annotate(
                c=Count("id")
            ):
                if r["d"]:
                    daily[r["d"].isoformat()] += r["c"]
        except Exception:
            logger.exception("user_usage %s %s", f.key, user_id)
    per_feature.sort(key=lambda x: x["count"], reverse=True)
    return {
        "user_id": user_id,
        "period": period or "all",
        "total": sum(x["count"] for x in per_feature),
        "segment": _dominant_segment(user_id, start),
        "per_feature": per_feature,
        "timeline": [{"date": d, "count": c} for d, c in sorted(daily.items())],
    }


# ── Churn / inaktiv ─────────────────────────────────────────────────────

def _last_activity_map():
    """user_id → oxirgi faollik sanasi (barcha feature bo'yicha eng kechki)."""
    last = {}
    for f in FEATURES:
        try:
            for r in _qs(f).values(f.user_field).annotate(m=Max(f.ts_field)):
                uid, m = r[f.user_field], r["m"]
                if not uid or not m:
                    continue
                d = m.date() if hasattr(m, "date") else m  # datetime/date
                if uid not in last or d > last[uid]:
                    last[uid] = d
        except Exception:
            logger.exception("last_activity %s", f.key)
    return last


def inactive_users(days=30, limit=100):
    """`days` kundan beri hech qanday faollik ko'rsatmagan (churn) userlar.

    Faqat kamida bir marta faol bo'lgan (biror vaqt ishlatgan) userlar — hech qachon
    ishlatmaganlar 'churn' emas. Oxirgi faollik + necha kun jim bo'lgani bilan.
    """
    today = timezone.localdate()
    cutoff = today - timedelta(days=days)
    last = _last_activity_map()
    stale = [(uid, d) for uid, d in last.items() if d < cutoff]
    stale.sort(key=lambda x: x[1])  # eng ko'p jim turganlari birinchi
    stale = stale[:limit]

    User = get_user_model()
    users = {u.id: u for u in User.objects.filter(id__in=[uid for uid, _ in stale])}
    out = []
    for uid, d in stale:
        u = users.get(uid)
        out.append({
            "user_id": uid,
            "name": (u.full_name or u.phone) if u else str(uid),
            "phone": u.phone if u else None,
            "role": u.role if u else None,
            "last_active": d.isoformat(),
            "inactive_days": (today - d).days,
        })
    return {"days": days, "count": len(out), "users": out}
