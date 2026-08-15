from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + konstantalar
from .common import _amt,_aware,_disp,_iso,_safe_section,_uname


class UserFullInfoSerializer(serializers.Serializer):
    """Admin 'to'liq user ma'lumoti' oynasi — tizimdagi BARCHA user datasi.

    `UserAdminDetailSerializer` (Umumiy tab) bermagan bo'limlar shu yerda:
    tibbiy karta, muolaja, parhez, salomatlik, to'lovlar, sharhlar, aloqa,
    referral va birlashtirilgan faollik tarixi (timeline).

    Har bo'lim mustaqil `@_safe_section` bilan himoyalangan — bittasi buzilsa
    butun javob 500 bermaydi, o'sha bo'lim bo'sh qaytadi.
    """

    medical = serializers.SerializerMethodField()
    treatments = serializers.SerializerMethodField()
    diet = serializers.SerializerMethodField()
    health = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    communication = serializers.SerializerMethodField()
    referrals = serializers.SerializerMethodField()
    activity = serializers.SerializerMethodField()

    # ── yordamchilar ────────────────────────────────────────────────────
    @staticmethod
    def _doctor_profile(obj):
        return getattr(obj, "doctor_profile", None)

    def _tr(self, val):
        """Translatable JSON dict → joriy til; oddiy string bo'lsa o'zi."""
        if isinstance(val, dict):
            return pick_for(self.context, val)
        return val

    # ── TIBBIY (medical) ────────────────────────────────────────────────
    @_safe_section(dict)
    def get_medical(self, obj):
        from app.medical.models import MedicalCard, MedicalCondition, MedicalNote

        card = MedicalCard.objects.filter(user=obj).first()
        card_data = None
        if card:
            card_data = {
                "blood_type": card.blood_type,
                "height_cm": card.height_cm,
                "weight_kg": _amt(card.weight_kg),
                "primary_disease": card.primary_disease,
                "current_status": card.current_status,
                "current_status_display": _disp(card, "current_status"),
                "notes": card.notes,
                "updated_at": _iso(card.updated_at),
            }

        cond_qs = (
            MedicalCondition.objects.filter(user=obj)
            .order_by("-discovered_at", "-created_at")
        )
        notes_qs = (
            MedicalNote.objects.filter(user=obj)
            .select_related("created_by")
            .order_by("-created_at")
        )

        # Analizlar — model boshqacha bo'lishi ehtimoliga qarshi alohida guard.
        analyses, analyses_count = [], 0
        try:
            from app.medical.models import Analysis

            an_qs = Analysis.objects.filter(patient=obj).order_by("-created_at")
            analyses_count = an_qs.count()
            analyses = [
                {
                    "id": a.id,
                    "title": a.title,
                    "type": self._tr(a.type.name) if getattr(a, "type", None) else None,
                    "status": a.status,
                    "status_display": _disp(a, "status"),
                    "recorded_at": _iso(getattr(a, "recorded_at", None)),
                    "created_at": _iso(getattr(a, "created_at", None)),
                }
                for a in an_qs[:FULL_INFO_CAP]
            ]
        except Exception:
            logger.exception("full-info analyses user=%s", obj.id)

        return {
            "card": card_data,
            "conditions": [
                {
                    "id": c.id,
                    "type": c.type,
                    "type_display": _disp(c, "type"),
                    "name": c.name,
                    "severity": c.severity,
                    "severity_display": _disp(c, "severity"),
                    "note": c.note,
                    "discovered_at": _iso(c.discovered_at),
                    "created_at": _iso(c.created_at),
                }
                for c in cond_qs[:FULL_INFO_CAP]
            ],
            "conditions_count": cond_qs.count(),
            "notes": [
                {
                    "id": n.id,
                    "text": n.text,
                    "created_by": _uname(n.created_by),
                    "created_at": _iso(n.created_at),
                }
                for n in notes_qs[:FULL_INFO_CAP]
            ],
            "notes_count": notes_qs.count(),
            "analyses": analyses,
            "analyses_count": analyses_count,
        }

    # ── MUOLAJA (treatments) ────────────────────────────────────────────
    @_safe_section(dict)
    def get_treatments(self, obj):
        from app.treatment.models import (
            DailyCalorieLimit,
            Treatment,
            TreatmentLog,
        )

        limit = DailyCalorieLimit.objects.filter(patient=obj).first()
        limit_data = None
        if limit:
            limit_data = {
                "calories": limit.calories,
                "carbs_limit": limit.carbs_limit,
                "protein_limit": limit.protein_limit,
                "fat_limit": limit.fat_limit,
                "notes": limit.notes,
                "set_by": _uname(getattr(limit, "set_by", None)),
                "updated_at": _iso(limit.updated_at),
            }

        items_qs = (
            Treatment.objects.filter(user=obj)
            .select_related("created_by")
            .order_by("-created_at")
        )
        logs_qs = TreatmentLog.objects.filter(user=obj).order_by("-date")

        return {
            "calorie_limit": limit_data,
            "items": [
                {
                    "id": t.id,
                    "type": t.type,
                    "type_display": _disp(t, "type"),
                    "title": t.title,
                    "status": t.status,
                    "status_display": _disp(t, "status"),
                    "dosage": t.dosage,
                    "duration": t.duration,
                    "notes": t.notes,
                    "time": t.time.strftime("%H:%M") if t.time else None,
                    "end_time": t.end_time.strftime("%H:%M") if t.end_time else None,
                    "end_date": _iso(t.end_date),
                    "is_as_needed": t.is_as_needed,
                    "created_by": _uname(t.created_by),
                    "created_at": _iso(t.created_at),
                }
                for t in items_qs[:FULL_INFO_CAP]
            ],
            "items_count": items_qs.count(),
            "logs": [
                {
                    "id": lg.id,
                    "treatment_title": lg.treatment_title,
                    "treatment_type": lg.treatment_type,
                    "status": lg.status,
                    "status_display": _disp(lg, "status"),
                    "date": _iso(lg.date),
                    "completed_at": _iso(lg.completed_at),
                    "scheduled_for": _iso(lg.scheduled_for),
                }
                for lg in logs_qs[:FULL_INFO_CAP]
            ],
            "logs_count": logs_qs.count(),
        }

    # ── PARHEZ (diet) ───────────────────────────────────────────────────
    @_safe_section(dict)
    def get_diet(self, obj):
        from app.diet_ai.models import (
            DietConversation,
            DietEntry,
            DietMessage,
            DietProfile,
            DietRestriction,
        )

        profile = DietProfile.objects.filter(user=obj).first()
        profile_data = None
        if profile:
            profile_data = {
                "goal": profile.goal,
                "goal_display": _disp(profile, "goal"),
                "target_weight_kg": _amt(profile.target_weight_kg),
                "pace_kg_week": _amt(profile.pace_kg_week),
                "activity_level": profile.activity_level,
                "activity_level_display": _disp(profile, "activity_level"),
                "meals_per_day": profile.meals_per_day,
                "restrictions": profile.restrictions or [],
                "motivation": profile.motivation,
                "updated_at": _iso(profile.updated_at),
            }

        entries_qs = DietEntry.objects.filter(user=obj).order_by("-date", "-created_at")
        restr_qs = (
            DietRestriction.objects.filter(patient=obj)
            .select_related("doctor", "doctor_profile__user")
            .order_by("-created_at")
        )

        return {
            "profile": profile_data,
            "entries": [
                {
                    "id": e.id,
                    "food_name": e.food_name,
                    "calories": e.calories,
                    "carbs_grams": e.carbs_grams,
                    "protein_grams": e.protein_grams,
                    "fat_grams": e.fat_grams,
                    "source": e.source,
                    "source_display": _disp(e, "source"),
                    "meal_type": e.meal_type,
                    "glycemic_load": e.glycemic_load,
                    "date": _iso(e.date),
                    "created_at": _iso(e.created_at),
                }
                for e in entries_qs[:FULL_INFO_CAP]
            ],
            "entries_count": entries_qs.count(),
            "conversations_count": DietConversation.objects.filter(user=obj).count(),
            "messages_count": DietMessage.objects.filter(
                conversation__user=obj
            ).count(),
            "restrictions": [
                {
                    "id": r.id,
                    "rule": r.rule,
                    "reason": r.reason,
                    "is_active": r.is_active,
                    "doctor": _uname(getattr(r, "doctor", None))
                    or (
                        _uname(r.doctor_profile.user)
                        if getattr(r, "doctor_profile", None)
                        else None
                    ),
                    "created_at": _iso(r.created_at),
                }
                for r in restr_qs[:FULL_INFO_CAP]
            ],
        }

    # ── SALOMATLIK (health) ─────────────────────────────────────────────
    @_safe_section(dict)
    def get_health(self, obj):
        from app.health_packages.models import (
            DailySituationCheckup,
            HealthIndicator,
        )

        # Har indicator_type bo'yicha eng oxirgi qiymat
        latest = {}
        readings = []
        ind_qs = (
            HealthIndicator.objects.filter(user=obj)
            .select_related("indicator_type")
            .order_by("-recorded_at")
        )
        for ind in ind_qs[:200]:
            entry = {
                "name": pick_for(self.context, ind.indicator_type.name),
                "value": ind.display_value,
                "value_secondary": ind.value_secondary,
                "unit": ind.indicator_type.unit,
                "icon": ind.indicator_type.icon,
                "source": ind.source,
                "recorded_at": _iso(ind.recorded_at),
            }
            if ind.indicator_type_id not in latest:
                latest[ind.indicator_type_id] = entry
            if len(readings) < FULL_INFO_CAP:
                readings.append(entry)

        checkups_qs = DailySituationCheckup.objects.filter(user=obj).order_by("-date")

        return {
            "indicators_latest": list(latest.values()),
            "recent_readings": readings,
            "checkups": [
                {
                    "status": c.status,
                    "status_display": _disp(c, "status"),
                    "note": c.note,
                    "date": _iso(c.date),
                }
                for c in checkups_qs[:FULL_INFO_CAP]
            ],
            "checkups_count": checkups_qs.count(),
        }

    # ── TO'LOVLAR (payments) ────────────────────────────────────────────
    @_safe_section(dict)
    def get_payments(self, obj):
        from app.payments.models import (
            AtmosSavedCard,
            DoctorTariffPurchase,
            OfflinePayment,
            Payment,
            ProSubscription,
        )

        pay_qs = Payment.objects.filter(user=obj).order_by("-created_at")
        subs_qs = (
            ProSubscription.objects.filter(user=obj)
            .select_related("plan")
            .order_by("-created_at")
        )
        purch_qs = (
            DoctorTariffPurchase.objects.filter(patient=obj)
            .select_related("doctor__user", "tariff")
            .order_by("-created_at")
        )
        offline_qs = (
            OfflinePayment.objects.filter(patient=obj)
            .select_related("doctor__user")
            .order_by("-created_at")
        )
        cards_qs = AtmosSavedCard.objects.filter(user=obj).order_by("-created_at")

        result = {
            "payments": [
                {
                    "id": p.id,
                    "amount": _amt(p.amount),
                    "provider": p.provider,
                    "provider_display": _disp(p, "provider"),
                    "status": p.status,
                    "status_display": _disp(p, "status"),
                    "purpose": p.purpose,
                    "purpose_display": _disp(p, "purpose"),
                    "created_at": _iso(p.created_at),
                    "completed_at": _iso(p.completed_at),
                }
                for p in pay_qs[:FULL_INFO_CAP]
            ],
            "payments_count": pay_qs.count(),
            "pro_subscriptions": [
                {
                    "id": s.id,
                    "plan_name": self._tr(
                        (s.plan_snapshot or {}).get("name")
                        or (s.plan.name if s.plan else None)
                    ),
                    "is_active": s.is_active,
                    "granted_by_admin": bool(
                        (s.plan_snapshot or {}).get("granted_by_admin")
                    ),
                    "starts_at": _iso(s.starts_at),
                    "expires_at": _iso(s.expires_at),
                    "created_at": _iso(s.created_at),
                }
                for s in subs_qs[:FULL_INFO_CAP]
            ],
            "tariff_purchases": [
                {
                    "id": tp.id,
                    "tariff_name": self._tr(
                        (tp.tariff_snapshot or {}).get("name")
                        or (tp.tariff.name if tp.tariff else None)
                    ),
                    "doctor": _uname(tp.doctor.user) if tp.doctor else None,
                    "amount_paid": _amt(tp.amount_paid),
                    "source": tp.source,
                    "starts_at": _iso(tp.starts_at),
                    "expires_at": _iso(tp.expires_at),
                    "created_at": _iso(tp.created_at),
                }
                for tp in purch_qs[:FULL_INFO_CAP]
            ],
            "tariff_purchases_count": purch_qs.count(),
            "offline_payments": [
                {
                    "id": op.id,
                    "amount": _amt(op.amount),
                    "doctor": _uname(op.doctor.user) if op.doctor else None,
                    "status": op.status,
                    "status_display": _disp(op, "status"),
                    "created_at": _iso(op.created_at),
                }
                for op in offline_qs[:FULL_INFO_CAP]
            ],
            "atmos_cards": [
                {
                    "id": c.id,
                    "pan_last4": getattr(c, "pan_last4", None),
                    "card_holder": c.card_holder,
                    "is_primary": c.is_primary,
                    "created_at": _iso(c.created_at),
                }
                for c in cards_qs
            ],
            "doctor": None,
        }

        # Doctor tomoni — DoctorProfile bo'lsa (sotuvlar, tariflar, payout, topup)
        profile = self._doctor_profile(obj)
        if profile:
            from app.payments.models import (
                BalanceTopup,
                DoctorTariff,
                PayoutRequest,
            )

            tariffs_qs = DoctorTariff.objects.filter(doctor=profile).order_by(
                "-created_at"
            )
            sales_qs = (
                DoctorTariffPurchase.objects.filter(doctor=profile)
                .select_related("patient", "tariff")
                .order_by("-created_at")
            )
            payouts_qs = PayoutRequest.objects.filter(doctor=profile).order_by(
                "-created_at"
            )
            topups_qs = BalanceTopup.objects.filter(doctor=profile).order_by(
                "-created_at"
            )

            result["doctor"] = {
                "tariffs": [
                    {
                        "id": tf.id,
                        "name": self._tr(tf.name),
                        "price": _amt(tf.price),
                        "status": tf.status,
                        "status_display": _disp(tf, "status"),
                        "is_active": tf.is_active,
                        "created_at": _iso(tf.created_at),
                    }
                    for tf in tariffs_qs[:FULL_INFO_CAP]
                ],
                "sales": [
                    {
                        "id": s.id,
                        "tariff_name": self._tr(
                            (s.tariff_snapshot or {}).get("name")
                            or (s.tariff.name if s.tariff else None)
                        ),
                        "patient": _uname(s.patient),
                        "amount_paid": _amt(s.amount_paid),
                        "doctor_earnings": _amt(getattr(s, "doctor_earnings", None)),
                        "commission_amount": _amt(
                            getattr(s, "commission_amount", None)
                        ),
                        "created_at": _iso(s.created_at),
                    }
                    for s in sales_qs[:FULL_INFO_CAP]
                ],
                "sales_count": sales_qs.count(),
                "payout_requests": [
                    {
                        "id": pr.id,
                        "amount": _amt(pr.amount),
                        "status": pr.status,
                        "status_display": _disp(pr, "status"),
                        "created_at": _iso(pr.created_at),
                        "processed_at": _iso(getattr(pr, "processed_at", None)),
                    }
                    for pr in payouts_qs[:FULL_INFO_CAP]
                ],
                "topups": [
                    {
                        "id": tu.id,
                        "amount": _amt(tu.amount),
                        "created_at": _iso(tu.created_at),
                    }
                    for tu in topups_qs[:FULL_INFO_CAP]
                ],
            }

        return result

    # ── SHARHLAR (reviews) ──────────────────────────────────────────────
    @_safe_section(dict)
    def get_reviews(self, obj):
        from app.feedbacks.models import Review

        written_qs = (
            Review.objects.filter(patient=obj)
            .select_related("doctor__user")
            .prefetch_related("tags")
            .order_by("-created_at")
        )
        written = [
            {
                "id": r.id,
                "doctor": _uname(r.doctor.user) if r.doctor else None,
                "rating": r.rating,
                "comment": r.comment,
                "tags": [t.label_uz for t in r.tags.all()],
                "is_edited": r.is_edited,
                "created_at": _iso(r.created_at),
            }
            for r in written_qs[:FULL_INFO_CAP]
        ]

        received = []
        received_count = 0
        profile = self._doctor_profile(obj)
        if profile:
            recv_qs = (
                Review.objects.filter(doctor=profile)
                .select_related("patient")
                .prefetch_related("tags")
                .order_by("-created_at")
            )
            received_count = recv_qs.count()
            received = [
                {
                    "id": r.id,
                    "patient": _uname(r.patient),
                    "rating": r.rating,
                    "comment": r.comment,
                    "tags": [t.label_uz for t in r.tags.all()],
                    "created_at": _iso(r.created_at),
                }
                for r in recv_qs[:FULL_INFO_CAP]
            ]

        return {
            "written": written,
            "written_count": written_qs.count(),
            "received": received,
            "received_count": received_count,
        }

    # ── ALOQA (chat / calls / notifications / devices) ──────────────────
    @_safe_section(dict)
    def get_communication(self, obj):
        from app.chat.models import CallSession, ChatRoom
        from app.notifications.models import DeviceToken, Notification

        rooms_qs = (
            ChatRoom.objects.filter(participants=obj)
            .prefetch_related("participants")
            .annotate(msg_count=Count("messages"), last_msg=Max("messages__created_at"))
            .order_by("-updated_at")
        )
        rooms = []
        for room in rooms_qs[:FULL_INFO_CAP]:
            other = next(
                (p for p in room.participants.all() if p.id != obj.id), None
            )
            rooms.append(
                {
                    "id": room.id,
                    "room_type": room.room_type,
                    "other_party": _uname(other),
                    "message_count": room.msg_count,
                    "last_message_at": _iso(room.last_msg),
                    "is_active": room.is_active,
                    "updated_at": _iso(room.updated_at),
                }
            )

        calls_qs = (
            CallSession.objects.filter(Q(caller=obj) | Q(callee=obj))
            .select_related("caller", "callee")
            .order_by("-created_at")
        )
        calls = []
        for c in calls_qs[:FULL_INFO_CAP]:
            outgoing = c.caller_id == obj.id
            other = c.callee if outgoing else c.caller
            calls.append(
                {
                    "id": c.id,
                    "call_type": c.call_type,
                    "status": c.status,
                    "status_display": _disp(c, "status"),
                    "direction": "out" if outgoing else "in",
                    "other_party": _uname(other),
                    "duration": getattr(c, "duration", None),
                    "created_at": _iso(c.created_at),
                }
            )

        notif_qs = Notification.objects.filter(user=obj).order_by("-created_at")
        devices_qs = DeviceToken.objects.filter(user=obj).order_by("-last_used_at")

        return {
            "chat_rooms": rooms,
            "chat_rooms_count": rooms_qs.count(),
            "calls": calls,
            "calls_count": calls_qs.count(),
            "notifications": [
                {
                    "id": n.id,
                    "type": n.type,
                    "type_display": _disp(n, "type"),
                    "app_scope": n.app_scope,
                    "title": n.title,
                    "body": n.body,
                    "is_read": n.is_read,
                    "created_at": _iso(n.created_at),
                }
                for n in notif_qs[:FULL_INFO_CAP]
            ],
            "notifications_count": notif_qs.count(),
            "devices": [
                {
                    "id": d.id,
                    "platform": d.platform,
                    "token_type": d.token_type,
                    "app_scope": d.app_scope,
                    "device_name": d.device_name,
                    "app_version": d.app_version,
                    "is_active": d.is_active,
                    "last_used_at": _iso(d.last_used_at),
                }
                for d in devices_qs[:FULL_INFO_CAP]
            ],
        }

    # ── REFERRAL ────────────────────────────────────────────────────────
    @_safe_section(dict)
    def get_referrals(self, obj):
        referred_by = getattr(obj, "referred_by", None)
        refs_qs = User.objects.filter(referred_by=obj).order_by("-date_joined")
        return {
            "referral_code": obj.referral_code,
            "referred_by": (
                {
                    "id": referred_by.id,
                    "full_name": _uname(referred_by),
                    "phone": referred_by.phone,
                    "role": referred_by.role,
                }
                if referred_by
                else None
            ),
            "referrals": [
                {
                    "id": u.id,
                    "full_name": _uname(u),
                    "phone": u.phone,
                    "role": u.role,
                    "date_joined": _iso(u.date_joined),
                }
                for u in refs_qs[:FULL_INFO_CAP]
            ],
            "referrals_count": refs_qs.count(),
        }

    # ── FAOLLIK TARIXI (activity timeline) ──────────────────────────────
    @_safe_section(list)
    def get_activity(self, obj):
        events = []

        def push(icon, title, subtitle, ts):
            if ts is None:
                return
            events.append(
                {
                    "icon": icon,
                    "title": title,
                    "subtitle": subtitle,
                    "timestamp": _iso(ts),
                    "_k": _aware(ts),
                }
            )

        # Ro'yxatdan o'tish
        push("👤", "Ro'yxatdan o'tdi", _disp(obj, "role") or obj.role, obj.date_joined)

        # Har manba mustaqil try — bittasi ishlamasa qolganlari qoladi
        def source(fn):
            try:
                fn()
            except Exception:
                logger.exception("activity source user=%s", obj.id)

        def _appointments():
            from app.meetings.models import Appointment

            for a in (
                Appointment.objects.filter(patient=obj)
                .select_related("doctor__user")
                .order_by("-created_at")[:20]
            ):
                doc = a.doctor.user.full_name if a.doctor else None
                push("📅", f"Qabul: {_disp(a, 'status')}", doc, a.created_at)

        def _payments():
            from app.payments.models import Payment

            for p in Payment.objects.filter(user=obj).order_by("-created_at")[:20]:
                push(
                    "💳",
                    f"To'lov: {_disp(p, 'status')}",
                    f"{_amt(p.amount)} — {_disp(p, 'purpose')}",
                    p.created_at,
                )

        def _treatments():
            from app.treatment.models import Treatment, TreatmentLog

            for t in Treatment.objects.filter(user=obj).order_by("-created_at")[:15]:
                push("💊", "Muolaja qo'shildi", t.title, t.created_at)
            for lg in TreatmentLog.objects.filter(user=obj).order_by("-date")[:15]:
                push(
                    "✅",
                    f"Muolaja: {_disp(lg, 'status')}",
                    lg.treatment_title,
                    lg.completed_at or lg.date,
                )

        def _diet():
            from app.diet_ai.models import DietEntry

            for e in DietEntry.objects.filter(user=obj).order_by("-created_at")[:15]:
                push("🍽", "Ovqat qo'shildi", f"{e.food_name} — {e.calories} kcal", e.created_at)

        def _reviews():
            from app.feedbacks.models import Review

            for r in (
                Review.objects.filter(patient=obj)
                .select_related("doctor__user")
                .order_by("-created_at")[:15]
            ):
                doc = r.doctor.user.full_name if r.doctor else None
                push("⭐", f"Sharh yozdi ({r.rating}/5)", doc, r.created_at)

        def _medical():
            from app.medical.models import MedicalCondition, MedicalNote

            for c in MedicalCondition.objects.filter(user=obj).order_by("-created_at")[:15]:
                push("🩺", f"Kasallik: {_disp(c, 'type')}", c.name, c.created_at)
            for n in MedicalNote.objects.filter(user=obj).order_by("-created_at")[:15]:
                push("📝", "Shifokor izohi", (n.text or "")[:60], n.created_at)

        def _checkups():
            from app.health_packages.models import DailySituationCheckup

            for c in DailySituationCheckup.objects.filter(user=obj).order_by("-date")[:15]:
                push("😊", f"Kunlik holat: {_disp(c, 'status')}", c.note, c.date)

        def _calls():
            from app.chat.models import CallSession

            for c in (
                CallSession.objects.filter(Q(caller=obj) | Q(callee=obj))
                .select_related("caller", "callee")
                .order_by("-created_at")[:15]
            ):
                outgoing = c.caller_id == obj.id
                other = c.callee if outgoing else c.caller
                push(
                    "📞",
                    f"Qo'ng'iroq: {_disp(c, 'status')}",
                    ("→ " if outgoing else "← ") + (_uname(other) or ""),
                    c.created_at,
                )

        def _connections():
            from app.doctors.models import DoctorPatient

            for dp in (
                DoctorPatient.objects.filter(patient=obj)
                .select_related("doctor__user")
                .order_by("-created_at")[:15]
            ):
                doc = dp.doctor.user.full_name if dp.doctor else None
                push("🔗", "Shifokorga bog'landi", doc, dp.created_at)

        for fn in (
            _appointments,
            _payments,
            _treatments,
            _diet,
            _reviews,
            _medical,
            _checkups,
            _calls,
            _connections,
        ):
            source(fn)

        events.sort(key=lambda e: e["_k"], reverse=True)
        events = events[:ACTIVITY_CAP]
        for e in events:
            e.pop("_k", None)
        return events


