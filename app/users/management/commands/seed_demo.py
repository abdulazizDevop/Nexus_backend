"""Demo ma'lumotlari — hackathon ko'rsatuvi uchun to'liq stsenariy.

Yaratadi (IDEMPOTENT — qayta ishga tushirsa dublikat bo'lmaydi):
  - mutaxassisliklar
  - 2 ta tasdiqlangan shifokor (marketplace'da ko'rinadi)
  - 1 ta bemor: tibbiy karta, surunkali tashxis, navigator yo'l xaritasi,
    7 kunlik ko'rsatkichlar / muolaja loglari / kayfiyat yozuvlari
  - shifokor↔bemor bog'lanishi (ACCEPTED)
  - oila a'zosi (ACCEPTED) — oila kuzatuvi demosi uchun

Ishlatish:
    python manage.py seed_demo
    python manage.py seed_demo --reset   # avval demo user'larni o'chiradi
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()

DOCTOR_PHONE = "998901234501"
DOCTOR2_PHONE = "998901234504"
PATIENT_PHONE = "998901234502"
FAMILY_PHONE = "998901234503"
DEMO_PHONES = [DOCTOR_PHONE, DOCTOR2_PHONE, PATIENT_PHONE, FAMILY_PHONE]

SPECIALTIES = [
    ("Kardiolog", "Кардиолог", "Кардиолог", "heart"),
    ("Terapevt", "Терапевт", "Терапевт", "stethoscope"),
    ("Gastroenterolog", "Гастроэнтеролог", "Гастроэнтеролог", "stomach"),
    ("Endokrinolog", "Эндокринолог", "Эндокринолог", "gland"),
    ("Nevrolog", "Невролог", "Невролог", "brain"),
    ("Oftalmolog", "Офтальмолог", "Офтальмолог", "eye"),
]

INDICATOR_TYPES = [
    # (system_key, uz, ru, cyr, unit, value_format)
    ("blood_pressure", "Qon bosimi", "Артериальное давление", "Қон босими", "mm sim.", "range"),
    ("heart_rate", "Yurak urishi", "Пульс", "Юрак уриши", "bpm", "number"),
    ("weight", "Vazn", "Вес", "Вазн", "kg", "number"),
    ("glucose", "Qon qandi", "Глюкоза", "Қон қанди", "mmol/l", "number"),
    ("temperature", "Harorat", "Температура", "Ҳарорат", "°C", "number"),
    ("steps", "Qadam", "Шаги", "Қадам", "qadam", "number"),
]

ROADMAP = [
    # (order, type, status, title, description, specialty/analysis, due_in_days)
    ("education", "done", "Kasallik haqida tushuncha",
     "Gipertoniya nima va nima uchun bosimni nazorat qilish muhim.", None, None),
    ("analysis", "done", "Asosiy tahlillarni topshiring",
     "Umumiy qon tahlili, kreatinin, xolesterin — shifokor yo'llanmasi bo'yicha.",
     "blood_general", None),
    ("medication", "current", "Shifokor tayinlagan dorini muntazam ichish",
     "Retseptdagi tartibda, har kuni bir xil vaqtda. Ichgan-ichmaganingizni ilovada belgilang.",
     None, 30),
    ("lifestyle", "locked", "Tuz iste'molini kamaytiring",
     "Kuniga 5 grammdan oshirmaslik tavsiya etiladi (bir choy qoshiq).", None, 14),
    ("checkup", "locked", "Takroriy kardiolog ko'rigi",
     "Bir oylik bosim yozuvlari bilan boring — shifokor rejani moslashtiradi.",
     "kardiolog", 30),
]


class Command(BaseCommand):
    help = "Demo ma'lumotlarini yaratadi (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Avval demo foydalanuvchilarni o'chirib, qaytadan yaratadi",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            deleted, _ = User.objects.filter(phone__in=DEMO_PHONES).delete()
            self.stdout.write(f"  Eski demo ma'lumotlar o'chirildi ({deleted} obyekt)")

        specialties = self._specialties()
        doctor, doctor2 = self._doctors(specialties)
        patient = self._patient()
        self._link_doctor_patient(doctor, patient)
        family = self._family(patient)
        condition = self._medical(patient, doctor)
        self._roadmap(condition, patient)
        treatments = self._treatments(patient, doctor)
        self._history(patient, treatments)

        self.stdout.write(self.style.SUCCESS("\n  Demo ma'lumotlari tayyor:\n"))
        self.stdout.write(f"    Shifokor      {DOCTOR_PHONE}  {doctor.user.full_name} (Kardiolog, tasdiqlangan)")
        self.stdout.write(f"    Shifokor 2    {DOCTOR2_PHONE}  {doctor2.user.full_name}")
        self.stdout.write(f"    Bemor         {PATIENT_PHONE}  {patient.full_name}")
        self.stdout.write(f"    Oila a'zosi   {FAMILY_PHONE}  {family.full_name}")
        self.stdout.write(
            "\n  Login uchun bu raqamlarni .env'dagi BYPASS_PHONE_NUMBERS ga qo'shing "
            "→ OTP kodi: 0000\n"
        )

    # --- bo'limlar ---

    def _specialties(self):
        from app.doctors.models import Specialty

        out = {}
        for uz, ru, cyr, icon in SPECIALTIES:
            obj = Specialty.objects.filter(name__uz=uz).first()
            if not obj:
                obj = Specialty.objects.create(
                    name={"uz": uz, "ru": ru, "cyr": cyr}, icon=icon
                )
            out[uz] = obj
        self.stdout.write(f"  Mutaxassisliklar: {len(out)}")
        return out

    def _doctors(self, specialties):
        from app.doctors.models import DoctorProfile

        def make(phone, full_name, spec, years, price, bio, workplace):
            user, _ = User.objects.get_or_create(
                phone=phone,
                defaults={"full_name": full_name, "role": "doctor", "active_role": "doctor"},
            )
            profile, _ = DoctorProfile.objects.update_or_create(
                user=user,
                defaults={
                    "specialty": spec,
                    "bio": bio,
                    "experience_years": years,
                    "workplace": workplace,
                    "is_verified": True,
                    "accepts_online": True,
                    "accepts_offline": True,
                    "marketplace_visible": True,
                    "consultation_enabled": True,
                    "consultation_price": Decimal(price),
                    "consultation_duration_min": 30,
                    # Moderatsiyadan o'tgan holatda — demo'da darhol booking ochiq
                    "consultation_status": DoctorProfile.ConsultationStatus.APPROVED,
                },
            )
            return profile

        d1 = make(
            DOCTOR_PHONE, "Aziza Karimova", specialties["Kardiolog"], 11, "150000",
            "Kardiolog. Arterial gipertoniya va yurak-qon tomir kasalliklari bo'yicha "
            "11 yillik tajriba. Bemorni uzoq muddat kuzatib borishga ixtisoslashgan.",
            "Respublika kardiologiya markazi",
        )
        d2 = make(
            DOCTOR2_PHONE, "Sardor Rasulov", specialties["Gastroenterolog"], 7, "120000",
            "Gastroenterolog. Oshqozon-ichak kasalliklari, parhez rejalari.",
            "Toshkent tibbiyot akademiyasi klinikasi",
        )
        self.stdout.write("  Shifokorlar: 2 (tasdiqlangan)")
        return d1, d2

    def _patient(self):
        patient, created = User.objects.get_or_create(
            phone=PATIENT_PHONE,
            defaults={
                "full_name": "Karim Toshmatov",
                "role": "patient",
                "sex": "male",
            },
        )
        if created or not patient.birth_date:
            patient.birth_date = timezone.localdate() - timedelta(days=365 * 58)
            patient.save(update_fields=["birth_date"])
        self.stdout.write(f"  Bemor: {patient.full_name}")
        return patient

    def _link_doctor_patient(self, doctor, patient):
        from app.doctors.models import DoctorPatient

        DoctorPatient.objects.update_or_create(
            doctor=doctor, patient=patient,
            defaults={
                "status": DoctorPatient.Status.ACCEPTED,
                "responded_at": timezone.now(),
            },
        )
        self.stdout.write("  Shifokor↔bemor bog'lanishi: ACCEPTED")

    def _family(self, patient):
        from app.family.models import FamilyLink

        member, _ = User.objects.get_or_create(
            phone=FAMILY_PHONE,
            defaults={"full_name": "Nilufar Toshmatova", "role": "patient", "sex": "female"},
        )
        FamilyLink.objects.update_or_create(
            patient=patient, member=member,
            defaults={
                "relation": FamilyLink.Relation.FARZAND,
                "status": FamilyLink.Status.ACCEPTED,
                "responded_at": timezone.now(),
            },
        )
        self.stdout.write("  Oila a'zosi: ACCEPTED (farzand)")
        return member

    def _medical(self, patient, doctor):
        from app.medical.models import MedicalCard, MedicalCondition

        MedicalCard.objects.update_or_create(
            user=patient,
            defaults={
                "blood_type": "O+",
                "height_cm": 174,
                "weight_kg": Decimal("86.0"),
                "primary_disease": "Arterial gipertoniya",
                "notes": "Bosim 3 yildan beri kuzatilmoqda. Shifokor nazoratida.",
                "updated_by": doctor.user,
            },
        )
        condition, _ = MedicalCondition.objects.update_or_create(
            user=patient, name="Arterial gipertoniya",
            defaults={
                "type": MedicalCondition.Type.CHRONIC,
                "severity": MedicalCondition.Severity.MEDIUM,
                "icd10": "I10",
                "source": MedicalCondition.DiagnosisSource.DOCTOR,
                "is_active": True,
                "discovered_at": timezone.localdate() - timedelta(days=20),
                "added_by": doctor.user,
                "plain_explanation": (
                    "Gipertoniya — qon bosimining doimiy ravishda yuqori bo'lishi. "
                    "Yurak qonni haydashda ko'proq kuch sarflaydi va vaqt o'tishi bilan "
                    "bu yurak hamda tomirlarni charchatadi. Bu tashxis bilan millionlab "
                    "odamlar to'laqonli hayot kechiradi — asosiysi, bosimni nazoratda tutish."
                ),
                "what_to_watch": [
                    "Ertalabki va kechki bosim ko'rsatkichlari",
                    "Bosh og'rig'i yoki bosh aylanishi qaytalansa",
                    "Oyoqlarda shish paydo bo'lsa",
                ],
                "red_flags": [
                    {"text": "Bosim 180/110 dan oshsa va tushmasa",
                     "action": "Zudlik bilan 103 ga qo'ng'iroq qiling",
                     "severity": "emergency"},
                    {"text": "Ko'krak qafasida og'riq yoki siqilish",
                     "action": "Zudlik bilan 103 ga qo'ng'iroq qiling",
                     "severity": "emergency"},
                    {"text": "Nutq buzilishi, yuz yoki qo'lda uvishish",
                     "action": "Zudlik bilan tez yordam chaqiring",
                     "severity": "emergency"},
                ],
            },
        )
        MedicalCondition.objects.get_or_create(
            user=patient, name="Penitsillin",
            defaults={
                "type": MedicalCondition.Type.ALLERGY,
                "severity": MedicalCondition.Severity.HIGH,
                "note": "Toshma va qichishish bilan namoyon bo'ladi.",
                "added_by": doctor.user,
            },
        )
        self.stdout.write("  Tibbiy karta + tashxis (I10) + allergiya")
        return condition

    def _roadmap(self, condition, patient):
        from app.medical.models import RoadmapStep

        today = timezone.localdate()
        for i, (typ, status, title, desc, extra, due_days) in enumerate(ROADMAP, start=1):
            payload = None
            if typ == "analysis":
                payload = {"analysis_type": extra or "", "preparation": "Nahorga topshiriladi"}
            elif typ in ("consultation", "checkup"):
                payload = {"specialty": extra or "kardiolog",
                           "reason": "Davolanish natijasini baholash"}
            elif typ == "medication":
                payload = {"medication_name": "Shifokor retsepti bo'yicha", "dosage": "",
                           "times_per_day": 2, "daily_times": [480, 1200],
                           "duration_days": 30, "notes": "Ovqatdan keyin"}
            RoadmapStep.objects.update_or_create(
                condition=condition, order=i,
                defaults={
                    "user": patient,
                    "type": typ,
                    "status": status,
                    "title": title,
                    "description": desc,
                    "body": (
                        "Gipertoniyada qon bosimi doimiy yuqori bo'ladi. Bu holat ko'pincha "
                        "sezilarli belgisiz kechadi, shuning uchun muntazam o'lchash muhim. "
                        "To'g'ri rejim bilan bosim me'yorda ushlab turiladi."
                        if typ == "education" else ""
                    ),
                    "due_date": today + timedelta(days=due_days) if due_days else None,
                    "payload": payload,
                    "completed_at": timezone.now() if status == "done" else None,
                },
            )
        self.stdout.write(f"  Navigator yo'l xaritasi: {len(ROADMAP)} qadam")

    def _treatments(self, patient, doctor):
        from app.treatment.models import Treatment

        rows = [
            {
                "type": Treatment.Type.MEDICATION,
                "title": "Ertalabki bosim dorisi",
                "dosage": "Shifokor retsepti bo'yicha",
                "times": ["08:00:00"],
                "notes": "Nahorga, ovqatdan 30 daqiqa oldin.",
            },
            {
                "type": Treatment.Type.MEDICATION,
                "title": "Kechki bosim dorisi",
                "dosage": "Shifokor retsepti bo'yicha",
                "times": ["20:00:00"],
                "notes": "Kechki ovqatdan keyin.",
            },
            {
                "type": Treatment.Type.EXERCISE,
                "title": "Kunlik yurish (30 daqiqa)",
                "dosage": "",
                "times": ["18:00:00"],
                "notes": "Tez yurish tempida, o'zingizni yaxshi his qilsangiz.",
            },
        ]
        out = []
        for r in rows:
            t, _ = Treatment.objects.update_or_create(
                user=patient, title=r["title"],
                defaults={
                    "created_by": doctor.user,
                    "type": r["type"],
                    "status": Treatment.Status.ACTIVE,
                    "dosage": r["dosage"],
                    "times": r["times"],
                    "time": time.fromisoformat(r["times"][0]),
                    "repeat": Treatment.Repeat.DAILY,
                    "notes": r["notes"],
                },
            )
            out.append(t)
        self.stdout.write(f"  Muolajalar: {len(out)} ta (shifokor tayinlagan)")
        return out

    def _history(self, patient, treatments):
        """7 kunlik tarix: ko'rsatkichlar, muolaja loglari, kayfiyat."""
        from app.health_packages.models import (
            DailySituationCheckup, HealthIndicator, HealthIndicatorType,
        )
        from app.treatment.models import TreatmentLog

        types = {}
        for key, uz, ru, cyr, unit, fmt in INDICATOR_TYPES:
            obj = HealthIndicatorType.objects.filter(system_key=key).first()
            if not obj:
                obj = HealthIndicatorType.objects.create(
                    system_key=key, name={"uz": uz, "ru": ru, "cyr": cyr},
                    unit=unit, value_format=fmt,
                    category=HealthIndicatorType.Category.MANUAL, manual_entry=True,
                )
            types[key] = obj

        today = timezone.localdate()
        tz = timezone.get_current_timezone()

        def aware(day, hh, mm=0):
            return timezone.make_aware(datetime.combine(day, time(hh, mm)), tz)

        # Bosim: har kuni ertalab/kechqurun, sekin yaxshilanish tendensiyasi
        bp = [(148, 94), (145, 92), (147, 93), (142, 90), (139, 88), (137, 86), (134, 85)]
        n_ind = n_log = 0
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            sys_v, dia_v = bp[6 - offset]

            for hh, delta in ((7, 0), (21, -3)):
                _, created = HealthIndicator.objects.get_or_create(
                    user=patient, indicator_type=types["blood_pressure"],
                    recorded_at=aware(day, hh), source=HealthIndicator.Source.MANUAL,
                    defaults={"value": Decimal(sys_v + delta),
                              "value_secondary": Decimal(dia_v + delta), "date": day},
                )
                n_ind += int(created)

            _, c = HealthIndicator.objects.get_or_create(
                user=patient, indicator_type=types["heart_rate"],
                recorded_at=aware(day, 7, 5), source=HealthIndicator.Source.MANUAL,
                defaults={"value": Decimal(76 - offset % 3), "date": day},
            )
            n_ind += int(c)

            if offset in (6, 3, 0):
                _, c = HealthIndicator.objects.get_or_create(
                    user=patient, indicator_type=types["weight"],
                    recorded_at=aware(day, 7, 10), source=HealthIndicator.Source.MANUAL,
                    defaults={"value": Decimal(str(86.5 - (6 - offset) * 0.2)), "date": day},
                )
                n_ind += int(c)

            _, c = HealthIndicator.objects.get_or_create(
                user=patient, indicator_type=types["steps"],
                recorded_at=aware(day, 22), source=HealthIndicator.Source.MANUAL,
                defaults={"value": Decimal(4200 + offset * 350), "date": day},
            )
            n_ind += int(c)

            # Kayfiyat
            mood = ["normal", "good", "good", "normal", "good", "good", "good"][6 - offset]
            DailySituationCheckup.objects.update_or_create(
                user=patient, date=day,
                defaults={"status": mood,
                          "note": "O'zimni yaxshi his qilyapman." if mood == "good" else ""},
            )

            # Muolaja loglari — 3-kuni bitta doza o'tkazib yuborilgan (real ko'rinish)
            for t in treatments:
                slot = aware(day, int(t.times[0][:2]))
                skipped = (offset == 3 and t.title == "Kechki bosim dorisi")
                _, c = TreatmentLog.objects.update_or_create(
                    treatment=t, scheduled_for=slot,
                    defaults={
                        "user": patient,
                        "treatment_title": t.title,
                        "treatment_type": t.type,
                        "date": day,
                        "status": (TreatmentLog.Status.SKIPPED if skipped
                                   else TreatmentLog.Status.COMPLETED),
                        "completed_at": None if skipped else slot,
                    },
                )
                n_log += int(c)

        self.stdout.write(
            f"  7 kunlik tarix: {n_ind} ko'rsatkich, {n_log} muolaja logi, 7 kayfiyat yozuvi"
        )
