"""Navigator xizmat funksiyalari: AI natijasini modelga yotqizish, progress,
kontrakt payload'lari va AI kontekst yig'ish (§11: ism/telefon YO'Q)."""

import logging
from datetime import timedelta

from django.utils import timezone

from app.medical.models import MedicalCondition, RoadmapStep

logger = logging.getLogger("mediik.navigator")


def _step_payload(s: dict) -> dict | None:
    """Flat AI qadamidan kontrakt §2 payload'ini yig'adi."""
    t = s["type"]
    if t == "medication":
        return {
            "medication_name": s.get("medication_name") or s.get("title", ""),
            "dosage": s.get("dosage") or "",
            "times_per_day": s.get("times_per_day") or 1,
            "daily_times": s.get("daily_times") or [],
            "duration_days": s.get("duration_days") or 0,
            "notes": s.get("notes") or "",
        }
    if t == "analysis":
        return {
            "analysis_type": s.get("analysis_type") or "",
            "preparation": s.get("preparation") or "",
        }
    if t in ("consultation", "checkup"):
        return {
            "specialty": (s.get("specialty") or "").lower(),
            "reason": s.get("reason") or "",
        }
    return None  # lifestyle/education


def materialize_roadmap(condition: MedicalCondition, parsed: dict) -> None:
    """AI natijasidagi qadamlarni RoadmapStep qatorlariga aylantiradi.

    Birinchi qadam `current`, qolganlari `locked` (kontrakt StepStatus).
    """
    today = timezone.localdate()
    steps = sorted(parsed.get("steps") or [], key=lambda s: s.get("order") or 0)
    rows = []
    for i, s in enumerate(steps):
        due = None
        if s.get("due_in_days"):
            due = today + timedelta(days=int(s["due_in_days"]))
        rows.append(
            RoadmapStep(
                condition=condition,
                user=condition.user,
                patient_profile=condition.patient_profile,
                order=i + 1,
                type=s["type"],
                status=(
                    RoadmapStep.Status.CURRENT if i == 0 else RoadmapStep.Status.LOCKED
                ),
                title=s.get("title") or "",
                description=s.get("description") or "",
                body=s.get("body") or "",
                due_date=due,
                payload=_step_payload(s),
            )
        )
    RoadmapStep.objects.bulk_create(rows)


def apply_ai_fields(condition: MedicalCondition, parsed: dict) -> None:
    condition.plain_explanation = parsed.get("plain_explanation") or ""
    condition.what_to_watch = parsed.get("what_to_watch") or []
    condition.red_flags = parsed.get("red_flags") or []
    condition.save(
        update_fields=["plain_explanation", "what_to_watch", "red_flags"]
    )


def roadmap_progress(condition: MedicalCondition) -> dict:
    steps = RoadmapStep.objects.filter(condition=condition)
    total = steps.count()
    done = steps.filter(status=RoadmapStep.Status.DONE).count()
    return {
        "total_steps": total,
        "done_steps": done,
        "percent": int(done * 100 / total) if total else 0,
    }


def complete_step(step: RoadmapStep) -> list[int]:
    """Qadamni done qiladi, keyingi locked'ni current'ga o'tkazadi.

    Returns: ochilgan qadam id'lari.
    """
    if step.status != RoadmapStep.Status.DONE:
        step.status = RoadmapStep.Status.DONE
        step.completed_at = timezone.now()
        step.save(update_fields=["status", "completed_at"])

    unlocked = []
    has_current = RoadmapStep.objects.filter(
        condition=step.condition, status=RoadmapStep.Status.CURRENT
    ).exists()
    if not has_current:
        nxt = (
            RoadmapStep.objects.filter(
                condition=step.condition, status=RoadmapStep.Status.LOCKED
            )
            .order_by("order")
            .first()
        )
        if nxt:
            nxt.status = RoadmapStep.Status.CURRENT
            nxt.save(update_fields=["status"])
            unlocked.append(nxt.id)
    return unlocked


def build_patient_context(user, diagnosis: MedicalCondition | None) -> str:
    """AI kontekst (§11: ISM/TELEFON YO'Q — faqat yosh, jins, tibbiy)."""
    lines = []

    birth = getattr(user, "birth_date", None)
    if birth:
        today = timezone.localdate()
        age = today.year - birth.year - (
            (today.month, today.day) < (birth.month, birth.day)
        )
        lines.append(f"Yosh: {age}")
    if getattr(user, "sex", None):
        lines.append(f"Jins: {'Erkak' if user.sex == 'male' else 'Ayol'}")

    if diagnosis:
        dx = f"Tashxis: {diagnosis.name}"
        if diagnosis.icd10:
            dx += f" (ICD-10: {diagnosis.icd10})"
        lines.append(dx)
        steps = RoadmapStep.objects.filter(condition=diagnosis)
        if steps:
            lines.append("Yo'l xaritasi qadamlari:")
            for s in steps:
                lines.append(
                    f"  [step id={s.id}] #{s.order} ({s.type}, {s.status}) {s.title}"
                )

    try:
        from app.treatment.models import Treatment

        active = Treatment.objects.filter(
            user=user, status=Treatment.Status.ACTIVE
        )[:10]
        if active:
            lines.append(
                "Aktiv muolajalar: "
                + "; ".join(f"{t.title} {t.dosage}".strip() for t in active)
            )
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.health_packages.models import HealthIndicator

        recent = (
            HealthIndicator.objects.filter(user=user)
            .select_related("indicator_type")
            .order_by("-recorded_at")[:5]
        )
        if recent:
            from core.i18n import pick_translation

            lines.append(
                "So'nggi ko'rsatkichlar: "
                + "; ".join(
                    f"{pick_translation(i.indicator_type.name, 'uz')}: {i.display_value}"
                    for i in recent
                )
            )
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)


def recommended_doctors_for(specialty_items: list[dict], limit: int = 3) -> list[dict]:
    """Triaj tavsiyasidagi mutaxassisliklar bo'yicha platformadagi shifokorlar."""
    try:
        from app.doctors.models import DoctorProfile
        from django.db.models import Q

        q = Q()
        for item in specialty_items:
            for term in (item.get("code"), item.get("label")):
                if term:
                    q |= Q(specialty__name__icontains=term)
        if not q:
            return []
        out = []
        for p in (
            DoctorProfile.objects.filter(q, is_verified=True)
            .select_related("user", "specialty")[:limit]
        ):
            out.append(
                {
                    "id": p.id,
                    "full_name": p.user.full_name,
                    "specialty": getattr(p.specialty, "name", "") or "",
                    "photo_url": None,
                    "rating": p.rating,
                    "experience_years": p.experience_years,
                    "consultation_price": (
                        float(p.consultation_price) if p.consultation_price else None
                    ),
                    "is_online_available": bool(getattr(p, "is_online", False)),
                }
            )
        return out
    except Exception:  # noqa: BLE001 — tavsiya best-effort, xato bo'lsa bo'sh
        logger.warning("recommended_doctors_for xatosi", exc_info=True)
        return []
