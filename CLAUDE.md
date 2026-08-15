# Mediik Backend v1

## Loyiha haqida
Mediik — tibbiy xizmatlar agregator platformasi. Bemorlar shifokorlarni topadi, qabulga yoziladi, online/offline konsultatsiya oladi, muolajalarini kuzatadi. Shifokorlar bemorlarni boshqaradi, muolaja yozadi, jadval belgilaydi.

## Texnologiyalar
- **Backend:** Django 5 + DRF + drf-spectacular
- **Realtime:** Django Channels (WebSocket chat)
- **Auth:** JWT (SimpleJWT) + Telegram OTP (aiogram 3)
- **Async:** Celery + Redis (broker + cache)
- **Video:** LiveKit Cloud
- **Push:** Firebase FCM + APNs VoIP
- **Storage:** DigitalOcean Spaces (S3) + Bunny CDN
- **Payments:** paytechuz (Payme + Click + Uzum)
- **AI:** Google Gemini (diet/tavsiyalar)
- **Monitoring:** Sentry (errors) + Flower (tasks)
- **Deploy:** Docker Compose + Nginx + Certbot (SSL)
- **DB:** Env-driven — `POSTGRES_DB` bo'lsa PostgreSQL, bo'lmasa SQLite (dev)

## Arxitektura
```
Nginx (SSL, static, proxy)
  ↓
Django/Gunicorn (API) ─┬─→ Redis (broker/cache + Channels layer)
Daphne (WebSocket)     │
  ↓                    ├─→ Celery Worker (async tasks)
Telegram Bot           ├─→ Celery Beat (scheduled tasks)
(aiogram, polling)     └─→ Flower (monitoring :5555)
  ↓
LiveKit Cloud (video) | Firebase FCM (push) | DO Spaces+Bunny CDN (media)
Gemini (diet AI)      | paytechuz (payments) | Sentry (errors)
```

> **API kontrakt:** Endpoint ro'yxati va request/response namunalari `API_DOCS.md` da. Bu fayl arxitektura va kod yozish qoidalari uchun.

## Foydalanuvchi rollari
| Rol | Tavsif |
|-----|--------|
| `patient` | Bemor — qabulga yoziladi, muolaja kuzatadi, salomatlik ko'rsatkichlarini kiritadi |
| `doctor` | Shifokor — profil, jadval, qabul, muolaja yozish, bemorlarni kuzatish |
| `admin` | Boshqaruv — turli darajalar: super, simple, seller, customer_support |

## Admin turlari
| Tur | Vazifa |
|-----|--------|
| `super` | To'liq boshqaruv, rollarni o'zgartirish, doktorlarni tasdiqlash |
| `simple` | Oddiy admin operatsiyalari |
| `seller` | Referral code orqali doktorlarni jalb qilish |
| `customer_support` | Foydalanuvchi qo'llab-quvvatlashi |

## App tuzilishi
```
app/
├── auth/            # OTP, register, login, logout, referral, Telegram bot
├── users/           # User + Patient + DoctorProfile (Yandex Taxi identity), connections
├── doctors/         # Doctor profil, specialty, schedule, slots, certificates
├── meetings/        # Appointment booking, approve/reject, LiveKit video, start/accept-call
├── treatment/       # Muolaja CRUD, log, stats, streak, kaloriya limit
├── medical/         # Klinik kartochka, conditions (allergy/disease/...), notes, AI draft
├── health_packages/ # Kunlik kayfiyat (daily-checkup), salomatlik ko'rsatkichlari
├── chat/            # Doctor↔Patient real-time chat (Channels), call sessions, support chat
├── notifications/   # In-app feed + FCM/APNs device tokens + admin broadcast
├── payments/        # Pro obuna + Doctor tariflari (paytechuz: Payme/Click/Uzum)
├── diet_ai/         # Gemini ovqatlanish AI, photo analysis, restrictions, calorie tracking
└── feedbacks/       # Reviewlar (rating + tag + 24h edit + 30d cooldown)

core/
├── permissions.py   # Role-based: IsDoctor, IsPatient, IsSuperAdmin, IsAdminBase, ...
├── exceptions.py    # Custom DRF exception handler (user-friendly errors)
├── tasks.py         # BaseTask — Celery auto-retry + logging
├── middleware.py    # Request logging, scope context
├── logging.py       # JSON Lines log konfiguratsiyasi
├── validators.py    # (bo'sh)

services/
├── telegram.py      # send_otp_via_telegram, get_deeplink, send_telegram_message
├── livekit.py       # generate_room_name, create_token (video qo'ng'iroqlar)
├── firebase.py      # FCM push (notify() helper bilan ishlatiladi — app.notifications.utils)
├── apns_voip.py     # APNs VoIP (incoming call push iOS)
├── gemini.py        # Google Gemini API wrapper (diet AI)
├── storage.py       # S3 presigned URL + Bunny CDN signed URL
└── payments/        # Payment provider abstraction (base.py, payme.py, registry.py)
```

## To'lovlar tizimi (payments app)

### Ikki xil monetizatsiya

1. **Pro obuna** — patient uchun. Admin paneldan `ProPlan` (davomiylik + narx) va `ProFeatureFlag` (imkoniyatlar ro'yxati) dinamik boshqariladi. Kodda `from app.payments.utils import has_active_pro, has_pro_feature` orqali tekshiriladi.
2. **Doctor tariflari** — doctor o'zi yaratadi, admin moderatsiyadan o'tkazadi. Patient to'laganda pul platforma komissiyasini ushlab qolib, qolgan summani doctor `DoctorBalance` ga qo'shadi (atomic F() increment).

### Asosiy modellar

- `SystemSetting` — runtime-editable global config (`doctor_commission_percent` va h.k.). Ishlatish: `SystemSetting.get("key", default)` yoki `SystemSetting.set("key", value)`.
- `ProPlan`, `ProFeatureFlag`, `ProSubscription` — Pro obuna
- `DoctorTariff` — doctor tarifi (chegirma maydonlari bilan: foiz/so'm, hamma/new_patients, muddat, label)
- `DoctorTariffPurchase` — sotib olingan tarif + snapshot + komissiya hisobi
- `DoctorBalance` — doctor ichki hisobi
- `Payment` — umumiy to'lov yozuvi (`purpose`: pro_subscription | doctor_tariff)

### Moderatsiya qoidasi

`DoctorTariff.save()` — agar `status=approved` bo'lsa VA moderatsiya maydonlaridan (`name, description, price, duration_days, features`) biri o'zgarsa, status avtomatik `pending` ga qaytadi. **Chegirma maydonlari moderatsiya talab qilmaydi** — doctor aksiyani erkin boshqaradi.

### Webhook flow

`POST /api/v1/payments/webhook/payme/` → `verify_callback()` → order_id (`pro-{pid}` yoki `tariff-{pid}`) orqali Payment topiladi → `_complete_payment()` atomic transaction da:
- Pro uchun: `ProSubscription` yaratiladi (plan snapshot)
- Doctor tarif uchun: `DoctorTariffPurchase` yaratiladi, `SystemSetting["doctor_commission_percent"]` dan komissiya hisoblanadi, `DoctorBalance.add_earnings()` chaqiriladi

Idempotent — `Payment.status == completed` bo'lsa qaytadan ishlov bermaydi.

### Provider abstraction

`services/payments/` — har provider `BasePaymentProvider` dan meros oladi. Yangi provider qo'shish: shu papkaga yangi fayl + `registry.py` da `_register()` ga qo'shish. Hozir Payme/Click/Uzum paytechuz orqali ishlaydi.

## Reviews tizimi (feedbacks app)

### Modellar
- `Review` — `appointment` (OneToOne), `doctor`, `patient`, `patient_profile`, `rating` (1–5), `comment`, `tags` (M2M), `is_edited`
- `ReviewTag` — admin boshqaradigan oldindan belgilangan taglar. `sentiment`: `positive` | `negative`. Frontend rating'ga qarab faqat mos sentiment'ni ko'rsatadi.

### Qoidalar (model + serializer da enforce qilingan)
- Faqat `Appointment.status == COMPLETED` bo'lsa review yozish mumkin
- Bir appointment'ga **bitta** review (OneToOne)
- Shu doctor uchun **30 kun cooldown** — keyingi review faqat 30 kundan keyin
- **24 soat edit window** — yozilgandan keyin patient `PATCH`/`DELETE` qila oladi, keyin qotib qoladi
- **Tag sentiment moslik:** `rating ≥ 4` → faqat `positive` taglar; `rating ≤ 3` → faqat `negative` taglar. Aralash tanlov reject qilinadi.
- `Review.save()` da `appointment_id`'dan `doctor_id`, `patient_id` va `patient_profile_id` avtomatik to'ldiriladi

### Stats
`GET /feedbacks/reviews/?doctor_id=...` paginated reviewlar + `stats` qaytaradi: `average_rating`, `total_reviews`, `rating_distribution` (5..1), `filter_counts` (all/positive/critical), `top_tags` (top 5, percent bilan). Stats `type` filter'ga bog'liq emas — har doim doctor bo'yicha to'liq.

## Referral tizimi
- **Seller → Doctor:** Seller referral code bilan doctor register qiladi
- **Doctor → Doctor:** Doctor boshqa doctorni ham refer qila oladi
- **Doctor → Patient:** Patient QR scan yoki link orqali doctorga bog'lanadi
- Referral code doctor va seller uchun avtomatik generatsiya bo'ladi (8 belgili)
- Link format: `https://{APP_DOMAIN}/ref/{REFERRAL_CODE}`

## Asosiy flowlar

### Register (Telegram OTP)
1. POST `/auth/register/` — phone + role (+ referral_code ixtiyoriy)
2. Telegram deeplink qaytariladi → user botga o'tadi
3. Bot ism so'raydi → OTP generatsiya → Telegram orqali yuboradi
4. POST `/auth/register/verify/` — phone + code → User yaratiladi, JWT qaytariladi

### Login
1. POST `/auth/login/` — phone → OTP Telegram orqali yuboriladi
2. POST `/auth/login/verify/` — phone + code → JWT qaytariladi

### Appointment (Qabulga yozilish)
1. Patient: GET `/doctors/{doctor_id}/slots/?date=...` → bo'sh slotlar
2. Patient: POST `/meetings/patient/` → appointment yaratish
3. Doctor: POST `/meetings/doctor/{id}/approve/` → tasdiqlash (online bo'lsa LiveKit room yaratiladi)
4. **Call flow (yangi):** Caller `POST /{role}/{id}/start-call/` → callee'ga `incoming_call` push; callee `POST /{role}/{id}/accept-call/` → ikki tomon LiveKit token oladi (push yo'q). `join-call` deprecated.

### Muolaja
- Patient o'zi qo'shadi yoki doctor yozib beradi
- Har 15 daqiqada Celery vaqtga yaqin muolajalarni tekshirib Telegram + FCM eslatma yuboradi
- `interval_hours` bo'lsa time dan end_time gacha har X soatda eslatma
- `custom_days` bo'lsa faqat ko'rsatilgan kunlarda ("1,3,5" = Du, Chor, Ju)
- `end_date` bo'lsa muddati o'tganda avtomatik `status=completed`

### Push notification (FCM + APNs)
- Token registratsiya: `POST /notifications/devices/` (idempotent — `(user, device_id, app_scope)` unique)
- Yuborish kodda: `from app.notifications.utils import notify` → `notify(user, title, body, app_scope="patient"|"doctor", ...)`
- `app_scope` — bitta phone'da Patient va Doctor app login bo'lganda push to'g'ri app'ga borishi uchun. **Cross-app leak'ni oldini oladi.**
- iOS incoming call uchun alohida APNs VoIP (`token_type="voip"`) — backend chat/meeting `start-call` da yuboradi

## Identity model — Yandex Taxi
Bitta phone = bitta `User`. Har User'da `Patient` profil avtomatik yaratiladi. Doctor sifatida ishlash uchun `DoctorProfile` (admin verify qiladi). Bir User ham bemor, ham shifokor bo'la oladi — alohida JWT scope'da.

| Identity | PK | Vazifa |
|----------|-----|--------|
| **User** | `id` | Auth (phone, full_name, avatar). Bittadan ko'p emas. |
| **Patient** | `patient_id` | Bemor sifatida ish-context. Auto-yaratiladi. |
| **DoctorProfile** | `doctor_id` | Shifokor ish-context. `is_verified=True` bo'lgach to'liq ishlaydi. |

JWT da `scope` (`patient` | `doctor` | `admin`), `patient_id`, `doctor_id`, `active_role`. Permission'lar **scope**'ni JWT'dan o'qiydi — view'da `request.user.role` emas, `request.auth["scope"]` ishlat.

## Muhim qoidalar (MAJBURIY)
- Swagger da faqat kerakli endpointlar ko'rinadi, admin CRUD yashirilgan (`@extend_schema(exclude=True)`)
- `get_queryset()` da `swagger_fake_view` tekshiriladi (schema generation uchun)
- `AnonymousUser` ga `.role` qilish mumkin emas — har doim `is_authenticated` tekshir
- `get_serializer_class()` da default serializer qaytarish shart — swagger crashdan himoya
- Barcha vaqtlar `Asia/Tashkent` timezone da
- OTP kodi 4 ta raqam, 5 daqiqa amal qiladi
- Dev muhitda `DEFAULT_OTP_CODE=7777` bilan test qilsa bo'ladi
- Dev muhitda `DEFAULT_REFERRAL_CODE=MEDIIK01` default referral code
- Unique constraint bor joyda `create` da mavjud bo'lsa yangilash (upsert) — IntegrityError oldini olish
- Celery task da Django ORM ishlatganda `sync_to_async` kerak emas — worker sinxron ishlaydi
- Bot (aiogram) va Channels consumer da Django ORM ishlatganda `sync_to_async` **kerak** — asinxron context
- Property yoki method da boshqa app modelini import qilganda `try/except ImportError` bilan himoyalash — app hali yozilmagan bo'lishi mumkin
- Push yuborish — har doim `from app.notifications.utils import notify` orqali, hech qachon to'g'ridan-to'g'ri `services/firebase.py` ga tegmaslik. `app_scope` parametrini har doim aniq berish.
- Yangi profile ID maydonlari (`patient_profile_id`, `doctor_profile_id`) — yangi feature'larda ishlat. Eski `user`/`patient`/`doctor` FK lar additive saqlanadi (legacy).
- **Har bir yangi endpoint yoki o'zgarish yakunlangach, Postman da test qilish uchun to'liq request/response namunasi berilishi SHART** — URL, method, headers (Authorization), body (raw JSON), va kutilgan response (status code + JSON body)

## View yozish qoidalari
```python
# 1. Har doim queryset class level da bo'lishi kerak
queryset = Model.objects.none()  # Swagger uchun

# 2. get_queryset() da swagger_fake_view tekshirish
def get_queryset(self):
    if getattr(self, "swagger_fake_view", False):
        return Model.objects.none()
    return Model.objects.filter(user=self.request.user)

# 3. get_serializer_class() da AnonymousUser himoyasi
def get_serializer_class(self):
    if not hasattr(self.request, 'user') or not self.request.user.is_authenticated:
        return DefaultSerializer
    ...

# 4. Yashirish — swagger dan ko'rinmasligi uchun
@extend_schema(exclude=True)
def retrieve(self, ...):
    return super().retrieve(...)

# 5. Permission action bo'yicha
def get_permissions(self):
    if self.action == "me":
        return [IsAuthenticated()]
    return [IsSuperAdmin()]
```

## Buyruqlar

### Lokal ishga tushirish
```bash
# Virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows
source .venv/bin/activate      # Linux/Mac

# Kerakli paketlar
pip install -r requirements.txt

# Migratsiya
python manage.py makemigrations
python manage.py migrate

# Server
python manage.py runserver

# Telegram bot (alohida terminal)
python manage.py run_bot
```

### Docker deploy
```bash
# Dev serverga deploy
./deploy.sh

# Yoki qo'lda
docker compose up -d --build
docker compose exec web python manage.py migrate --noinput

# Loglarni ko'rish
docker compose logs -f web
docker compose logs -f bot
docker compose logs -f celery

# Servicelar holati
docker compose ps
```

### Migratsiyalar bilan ishlash
```bash
# Yangi migration yaratish
python manage.py makemigrations

# Barcha migratsiyalarni o'chirish va qayta yaratish (DEV ONLY)
find app -path "*/migrations/0*.py" -type f -delete
python manage.py makemigrations

# DB ni tozalash va qayta yaratish (DEV ONLY)
rm -f data/db.sqlite3
python manage.py migrate
```

### Test ma'lumotlar qo'shish
```bash
python manage.py shell -c "
from app.doctors.models import Specialty
from app.health_packages.models import HealthIndicatorType

specialties = [
    ('Kardiolog', '❤️'), ('Nevropatolog', '🧠'), ('Pediatr', '👶'),
    ('Terapevt', '🩺'), ('Stomatolog', '🦷'), ('Dermatolog', '🧴'),
    ('Urolog', '💧'), ('Ginekolog', '🩷'), ('Oftalmolog', '👁️'),
]
for name, icon in specialties:
    Specialty.objects.get_or_create(name=name, defaults={'icon': icon})

indicators = [
    ('Qadam', 'qadam', '🚶'), ('Yurak urishi', 'bpm', '❤️'),
    ('Uyqu', 'soat', '😴'), ('Vazn', 'kg', '⚖️'),
    ('Qon bosimi', 'mmHg', '🔴'), ('Harorat', '°C', '🌡️'),
    ('Kaloriya', 'kcal', '🔥'), ('Suv ichish', 'ml', '💧'),
]
for name, unit, icon in indicators:
    HealthIndicatorType.objects.get_or_create(name=name, defaults={'unit': unit, 'icon': icon})
print('Done!')
"
```

## Docker servicelar
| Service | Vazifa | Port |
|---------|--------|------|
| web | Django API (gunicorn) | 8000 |
| bot | Telegram bot (polling) | — |
| celery | Async worker (2 ta) | — |
| celery-beat | Davriy tasklar (har 15 min muolaja eslatma) | — |
| flower | Task monitoring (admin/mediik2026) | 5555 |
| redis | Broker + cache | 6379 |

## Domenlar
| Domen | Vazifa | Server IP |
|-------|--------|-----------|
| `api.dev.mediik.uz` | Dev backend | 188.166.4.222 |
| `api.prod.mediik.uz` | Production backend | 68.183.10.218 |
| `flower.dev.mediik.uz` | Flower monitoring | 188.166.4.222 |
| `app.dev.mediik.uz` | Universal Links (kelajak) | 188.166.4.222 |
| `app.mediik.uz` | Universal Links production (kelajak) | 68.183.10.218 |

## Monitoring
| Xizmat | URL | Vazifa |
|--------|-----|--------|
| Swagger | `https://api.dev.mediik.uz/docs/` | API hujjati |
| Health Check | `https://api.dev.mediik.uz/health/` | API, DB, Redis, Celery holati |
| Flower | `https://flower.dev.mediik.uz` | Celery task monitoring |
| Sentry | sentry.io | Error tracking (production) |
| Loglar | `data/mediik.log` | Server log fayli |

## Kelajak rejalari
1. PostgreSQL ga to'liq o'tish (prod env'da yoqilgan, dev SQLite)
2. Paynet integratsiyasi (Payme/Click/Uzum allaqachon paytechuz orqali)
3. Universal Links (iOS/Android deep linking — domain'lar tayyor, kontent yo'q)
4. FCM topics — broadcast'larni topic-based qilish
5. Admin panel API kengaytirish (statistika dashboard'lari)
6. Test coverage (positive + negative testlar)
