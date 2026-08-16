import logging
import os
import sys
from pathlib import Path
from datetime import timedelta

from celery.schedules import crontab
from dotenv import load_dotenv

import sentry_sdk
from corsheaders.defaults import default_headers

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = os.getenv("DEBUG", "False") == "True"

# TESTING flag — Django test runner DEBUG=False ishlatadi
TESTING = "test" in sys.argv or "pytest" in sys.argv[0]

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]


INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "channels",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
    # local
    "app.appinfo",
    "app.auth",
    "app.doctors",
    "app.feedbacks",
    "app.guides",
    "app.health_packages",
    "app.meetings",
    "app.payments",
    "app.treatment",
    "app.users",
    "app.chat",
    "app.medical",
    "app.notifications",
    "app.diet_ai",
    "app.health_ai",
    "app.pharmacy",
    "app.voice_ai",
    "app.analytics",
    "app.family",
    "app.tracking_ai",
    "app.navigator",
    # core — i18n helpers va management commands uchun (translate_existing va h.k.)
    "core",
    # paytechuz — Payme/Click/Uzum integratsiyasi (Transaction modeli)
    "paytechuz.integrations.django",
]

# Qo'lda (naqd) to'lov — tashqi gateway'siz xaridni DARHOL yakunlaydi.
# Faqat dev/test uchun: to'lovdan KEYINGI holatni Payme sandbox'ini kutmasdan
# sinash imkonini beradi. PROD'da HECH QACHON True qilinmasin — pulsiz xarid yaratadi.
MANUAL_PAYMENT_ENABLED = os.getenv("MANUAL_PAYMENT_ENABLED", "False") == "True"

# To'lovlar demo-rejimi: False (default) → to'lov boshlanish endpointlari
# 503 + "bu demo" javobini qaytaradi (app/payments/middleware.py). O'qish
# endpointlari ishlayveradi. Haqiqiy to'lov ulanganda .env'da True qilinadi.
PAYMENTS_ENABLED = os.getenv("PAYMENTS_ENABLED", "False") == "True"

AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.RequestContextMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Foydalanish analitikasi (Phase 2) — mos feature-path'larda JWT decode qilib
    # kunlik hisoblaydi. Best-effort, so'rovni hech qachon buzmaydi.
    "app.analytics.middleware.FeatureUsageMiddleware",
    # Demo: PAYMENTS_ENABLED=False bo'lsa to'lov endpointlari 503 + "bu demo".
    "app.payments.middleware.PaymentsDemoModeMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# DATABASES — env-driven:
if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "sslmode": os.getenv("POSTGRES_SSLMODE", "prefer"),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "db.sqlite3",
            # SQLite concurrent write muammolariga qarshi:
            "OPTIONS": {
                "timeout": 30,
                "init_command": (
                    "PRAGMA journal_mode=WAL;"
                    "PRAGMA synchronous=NORMAL;"
                    "PRAGMA busy_timeout=30000;"
                    "PRAGMA foreign_keys=ON;"
                ),
            },
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Tashkent"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media fayllar DO Spaces + Bunny CDN'ga saqlanadi.

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    # Pagination — barcha list view'lar uchun. Frontend `results` field bilan
    # mos keladi (data?.data?.results || data?.data || []).
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Soft-delete qilingan (is_active=False) yoki bekor qilingan user'lar eski JWT
    # bilan kira olmasin. Default False — har request'da user.is_active tekshiradi.
    "CHECK_USER_IS_ACTIVE": True,
}

# CORS
# Prod domenlari — CORS va CSRF ikkalasi uchun yagona manba (DRY).
_PROD_ORIGINS = [
    "https://admin.dev.mediik.uz",
    "https://admin.mediik.uz",
    "https://doctor.dev.mediik.uz",
    "https://doctor.mediik.uz",
    "https://mediik.uz",
    "https://www.mediik.uz",
    "https://account.mediik.uz",
    # Sog'liq Navigator web (Firebase Hosting ikkita domen beradi) + asosiy domen
    "https://mediik-42b6b.web.app",
    "https://mediik-42b6b.firebaseapp.com",
    "https://medway.mediik.uz",
]

CORS_ALLOW_ALL_ORIGINS = DEBUG


def _parse_origins(raw: str) -> list[str]:
    """Env'dan origin ro'yxatini o'qish — "http://a,https://b" yoki
    '["http://a","https://b"]' ikkala format ham qo'llab-quvvatlanadi.
    Har element bir marta tozalanadi (bracket/quote/bo'shliq)."""
    raw = raw.strip().strip("[").strip("]")
    cleaned = (o.strip().strip('"').strip("'") for o in raw.split(","))
    return [o for o in cleaned if o.startswith("http")]


CORS_ALLOWED_ORIGINS = _parse_origins(
    os.getenv("CORS_ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS", "")
)
if not DEBUG:
    for origin in _PROD_ORIGINS:
        if origin not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(origin)

# i18n custom header — admin/web/doctor mijozlar tanlangan tilni `X-Language` orqali
CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-language",
)


# === Production security headers ===
if not DEBUG and not TESTING:
    # HTTPS-only cookie'lar — production'da JWT cookie session bo'lmasa ham,
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False  # AngularJS-like clients X-CSRFToken o'qiydi

    # HTTP → HTTPS redirect (Nginx allaqachon qiladi, defense-in-depth)
    SECURE_SSL_REDIRECT = True
    # Nginx HTTPS terminate qilgani uchun Django request.is_secure() ni
    # X-Forwarded-Proto header'idan o'qiydi.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # HSTS — bir yil davomida brauzer faqat HTTPS bilan ulanishi shart
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Clickjacking himoyasi
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True  # legacy IE, harmless
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

    # CSRF trusted origins — admin paneli session uchun. CORS_ALLOWED_ORIGINS
    # bilan bir xil ro'yxat (_PROD_ORIGINS), lekin Django CSRF alohida talab qiladi.
    # Env orqali qo'shilgan origin'lar ham ishonchli bo'lsin (frontend deploy
    # manzili .env'dan kelsa CSRF'ga qo'lda qo'shish talab qilinmasin).
    CSRF_TRUSTED_ORIGINS = list(
        dict.fromkeys([*_PROD_ORIGINS, *CORS_ALLOWED_ORIGINS])
    )


# Swagger / drf-spectacular
SPECTACULAR_SETTINGS = {
    "TITLE": "Mediik API",
    "DESCRIPTION": "Medical appointment & healthcare platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    "SWAGGER_UI_SETTINGS": {
        "defaultModelsExpandDepth": -1,
    },
    "POSTPROCESSING_HOOKS": [
        "app.payments.openapi.add_webhook_paths",
        "core.openapi_hooks.annotate_translatable_fields",
    ],
    "ENUM_NAME_OVERRIDES": {
        "UserRoleEnum": [
            ("patient", "Patient"),
            ("doctor", "Doctor"),
            ("admin", "Admin"),
        ],
        "RegisterRoleEnum": [
            ("patient", "Patient"),
            ("doctor", "Doctor"),
        ],
        "UserSexEnum": [
            ("male", "Male"),
            ("female", "Female"),
        ],
        "UserAdminTypeEnum": [
            ("super", "Super"),
            ("simple", "Simple"),
            ("seller", "Seller"),
            ("customer_support", "Customer Support"),
        ],
        "DailySituationStatusEnum": [
            ("good", "Yaxshi"),
            ("normal", "O'rtacha"),
            ("bad", "Yomon"),
        ],
        "TreatmentLogStatusEnum": [
            ("completed", "Bajarildi"),
            ("skipped", "O'tkazib yuborildi"),
        ],
        "TreatmentTypeEnum": [
            ("medication", "Dori"),
            ("exercise", "Mashq"),
            ("diet", "Parhez"),
            ("water", "Suv ichish"),
            ("sleep", "Uyqu"),
        ],
        "TreatmentRepeatEnum": [
            ("daily", "Har kuni"),
            ("every_other_day", "Har ikki kuni"),
            ("three_times_week", "Har uch kuni"),
            ("weekly", "Haftalik"),
            ("biweekly", "Har ikki haftada"),
            ("monthly", "Oylik"),
            ("custom", "Maxsus"),
        ],
        "WeekdayEnum": [
            (0, "Dushanba"),
            (1, "Seshanba"),
            (2, "Chorshanba"),
            (3, "Payshanba"),
            (4, "Juma"),
            (5, "Shanba"),
            (6, "Yakshanba"),
        ],
        "AppointmentStatusEnum": [
            ("pending", "Kutilmoqda"),
            ("approved", "Tasdiqlangan"),
            ("rejected", "Rad etilgan"),
            ("cancelled", "Bekor qilingan"),
            ("completed", "Yakunlangan"),
        ],
        "MeetingTypeEnum": [
            ("online", "Online"),
            ("offline", "Offline"),
        ],
        # --- Status enum'lari (ko'p modellarda 'status' nomli choices bor) ---
        "AccountDeletionStatusEnum": [
            ("pending", "Kutilmoqda"),
            ("processed", "O'chirildi"),
            ("rejected", "Rad etildi"),
        ],
        "CallSessionStatusEnum": [
            ("ringing", "Jiringlamoqda"),
            ("active", "Faol"),
            ("completed", "Tugallangan"),
            ("missed", "Javobsiz"),
            ("rejected", "Rad etilgan"),
            ("cancelled", "Bekor qilingan"),
        ],
        "DoctorPatientStatusEnum": [
            ("pending", "Kutilmoqda"),
            ("accepted", "Qabul qilingan"),
            ("declined", "Rad etilgan"),
        ],
        "MedicalCardStatusEnum": [
            ("good", "Yaxshi"),
            ("normal", "O'rta"),
            ("bad", "Yomon"),
        ],
        "TreatmentStatusEnum": [
            ("active", "Faol"),
            ("paused", "To'xtatilgan"),
            ("completed", "Tugallangan"),
        ],
        "DoctorTariffModerationStatusEnum": [
            ("pending", "Kutilmoqda"),
            ("approved", "Tasdiqlangan"),
            ("rejected", "Rad etilgan"),
        ],
        # --- Role (Diet AI message turi User.Role bilan kollizion qilmasligi uchun) ---
        "DietMessageRoleEnum": [
            ("user", "User"),
            ("assistant", "Assistant"),
            ("system", "System"),
        ],
        # --- Language (Diet AI conversation va Medical AI draft) ---
        "LanguageEnum": [
            ("uz", "O'zbek"),
            ("uz-cyrl", "Ўзбек"),
            ("ru", "Русский"),
        ],
    },
}

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "mediikuzbot")

# === Eskiz.uz SMS Gateway ===
ESKIZ_BASE_URL = os.getenv("ESKIZ_BASE_URL", "https://notify.eskiz.uz")
ESKIZ_EMAIL = os.getenv("ESKIZ_EMAIL", "")
ESKIZ_PASSWORD = os.getenv("ESKIZ_PASSWORD", "")
# Sender ID — test uchun "4546", prod uchun moderatsiyadan o'tgan nick
ESKIZ_FROM = os.getenv("ESKIZ_FROM", "4546")

# Root Super Admin — hech kim manage qila olmaydi, o'zi hammani boshqaradi.
# Env'siz bo'sh — prod'da hardcoded default xavfli (audit H6).
ROOT_ADMIN_PHONE = os.getenv("ROOT_ADMIN_PHONE", "")

# Akkaunt o'chirish xabari root admin'dan tashqari shu Telegram chat_id larга ham
# boradi (vergul bilan). Default — qo'shimcha kuzatuvchi.
ACCOUNT_DELETION_NOTIFY_CHAT_IDS = [
    c.strip()
    for c in os.getenv("ACCOUNT_DELETION_NOTIFY_CHAT_IDS", "812258141").split(",")
    if c.strip()
]

# "Pul olindi-yu xizmat/yozuv yaratilmadi" (webhook side-effect xato, konsultatsiya
# bekor/expired band uchun kelган to'lov) — shu Telegram chat_id larга alert boradi.
# Hozircha qo'lda refund flow'ni ko'rinadigan qiladi (Sentry ham critical'ni oladi).
PAYMENT_ALERT_CHAT_IDS = [
    c.strip()
    for c in os.getenv("PAYMENT_ALERT_CHAT_IDS", "812258141").split(",")
    if c.strip()
]

# Firebase Admin SDK (push notifications)
FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH", str(BASE_DIR / "firebase.json")
)

# APNS VoIP (iOS PushKit — incoming call ringtone via CallKit)
# Certificate univeral — dev va prod uchun bir xil .p12 ishlatiladi
# Endpoint esa ENV orqali tanlanadi (APNS_VOIP_USE_SANDBOX=True/False)
APNS_VOIP_CERT_PATH = os.getenv(
    "APNS_VOIP_CERT_PATH", str(BASE_DIR / "secrets" / "voip_cert.pem")
)
APNS_VOIP_KEY_PATH = os.getenv(
    "APNS_VOIP_KEY_PATH", str(BASE_DIR / "secrets" / "voip_key.pem")
)
APNS_VOIP_TOPIC = os.getenv("APNS_VOIP_TOPIC", "com.mediik.patient.voip")
APNS_VOIP_USE_SANDBOX = os.getenv("APNS_VOIP_USE_SANDBOX", "False").lower() == "true"

# OTP
OTP_LENGTH = 4
OTP_EXPIRE_MINUTES = 2
# 4-raqamli OTP brute-force xavfini kamaytirish: shuncha noto'g'ri urinishdan
# keyin kod bekor qilinadi. Hujumchi 10000 variantni siliklab tushira olmaydi.
OTP_MAX_ATTEMPTS = 5

# App Domain (referral link uchun)
APP_DOMAIN = os.getenv("APP_DOMAIN", "app.dev.mediik.uz")

# Test kodlar — FAQAT DEBUG=True yoki test runner muhitida.
# Prod'da env'da set bo'lsa ham backend qabul qilmaydi (audit C3 — bypass'siz
# OTP verify xavfi). Lokal'da test uchun: DEBUG=True + DEFAULT_OTP_CODE=7777.
_ALLOW_TEST_CODES = DEBUG or TESTING
DEFAULT_REFERRAL_CODE = os.getenv("DEFAULT_REFERRAL_CODE") if _ALLOW_TEST_CODES else None
DEFAULT_OTP_CODE = os.getenv("DEFAULT_OTP_CODE") if _ALLOW_TEST_CODES else None

# Store review (Google Play / App Store) test akkaunti uchun OTP bypass:
# bu raqamlar uchun OTP YUBORILMAYDI, "0000" kod qabul qilinadi (reviewer real
# SMS/Telegram OTP ololmaydi — login ishlashi shart). Prod'da ham ishlaydi.
#
# XAVFSIZLIK: ENV-driven — repo'da hardcoded backdoor emas, env orqali kod
# deploy'siz o'chiriladi. Review/launch tugagach prod env'da BYPASS_PHONE_NUMBERS=""
# qo'yib BUTUNLAY o'chiring. Test akkaunt CLEAN/imtiyozsiz bo'lsin (PII/admin yo'q).
BYPASS_PHONE_NUMBERS: list[str] = [
    s.strip()
    for s in os.getenv("BYPASS_PHONE_NUMBERS", "").split(",")
    if s.strip()
]

# --- Payments (paytechuz) ---
# Barcha provayderlar uchun ACCOUNT_MODEL = app.payments.models.Payment.
# Paytechuz webhook'da `account_id` orqali Payment'ni topadi.
# IS_TEST_MODE — har provider alohida (sandbox/prod toggle).
# Kalitlar bo'lmagan provider PAYTECHUZ dict'ida qoladi-yu, services/payments/
# registry.py uni ishga tushirmaydi (kalitlar bo'sh bo'lsa).

PAYTECHUZ_TEST_MODE = os.getenv("PAYTECHUZ_TEST_MODE", "True").lower() == "true"

# Barcha provider'lar uchun umumiy kalitlar (DRY). Provider-specific kalitlar
# spread'dan keyin override qiladi (masalan PAYME'da ACCOUNT_FIELD).
_PAYTECHUZ_COMMON = {
    "ACCOUNT_MODEL": "app.payments.models.Payment",
    "ACCOUNT_FIELD": "id",
    "AMOUNT_FIELD": "amount",
    "ONE_TIME_PAYMENT": True,
    "IS_TEST_MODE": PAYTECHUZ_TEST_MODE,
}

PAYTECHUZ = {
    "PAYME": {
        **_PAYTECHUZ_COMMON,
        "PAYME_ID": os.getenv("PAYME_ID", ""),
        "PAYME_KEY": os.getenv("PAYME_KEY", ""),
        # Paycom merchant kabinetidagi "Реквизиты платёжа" → "Название Реквизита"
        # bilan to'liq mos kelishi shart. Default `id`, lekin Mediik kassasida
        # `balance_id` qilib sozlangan (kabinet o'zgartirib bo'lmaydi — security).
        "ACCOUNT_FIELD": os.getenv("PAYME_ACCOUNT_FIELD", "id"),
    },
    "CLICK": {
        **_PAYTECHUZ_COMMON,
        "SERVICE_ID": os.getenv("CLICK_SERVICE_ID", ""),
        "MERCHANT_ID": os.getenv("CLICK_MERCHANT_ID", ""),
        "MERCHANT_USER_ID": os.getenv("CLICK_MERCHANT_USER_ID", ""),
        "SECRET_KEY": os.getenv("CLICK_SECRET_KEY", ""),
        # Audit C6 — paytechuz `prepare` callback'ida Click yuborgan amount
        # Payment.amount bilan solishtirilishi uchun MAJBURIY. Yo'qligida
        # arzon (1 so'm) Click to'lovi qimmat (1M so'm) Payment'ni yakunlay olar
        # edi. Payme/Uzum'da allaqachon bor edi — Click'da yetishmas edi.
        "COMMISSION_PERCENT": float(os.getenv("CLICK_COMMISSION_PERCENT", "0")),
    },
}

# To'lovdan keyin user qaytadigan URL — Universal Links / App Links uchun.
# Format: https://app.mediik.uz/payment/return — `payment_id` va `status` query
# params runtime'da `services.payments.base.build_return_url()` qo'shadi.
# iOS AASA + Android assetlinks.json `app.mediik.uz`'da host qilingan bo'lsa,
# Mediik app avtomatik ochiladi (deep-link). App yo'q bo'lsa brauzer fallback.
PAYMENT_RETURN_URL = os.getenv(
    "PAYMENT_RETURN_URL", f"https://{APP_DOMAIN}/payment/return"
)

# Atmos (karta gateway — paytechuz'dan tashqari, direct API)
ATMOS = {
    "CONSUMER_KEY": os.getenv("ATMOS_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": os.getenv("ATMOS_CONSUMER_SECRET", ""),
    "STORE_ID": os.getenv("ATMOS_STORE_ID", ""),
    # Webhook body'da kelgan `api_key` shu qiymatga teng bo'lishi shart (auth)
    "API_KEY": os.getenv("ATMOS_API_KEY", ""),
    "BASE_URL": os.getenv("ATMOS_BASE_URL", "https://apigw.atmos.uz"),
    "IS_TEST_MODE": os.getenv("ATMOS_TEST_MODE", "true").lower() == "true",
    # Token cache TTL (sek). Atmos token 3600s, biz 50min cache qilamiz (10min buffer).
    "TOKEN_CACHE_TTL": int(os.getenv("ATMOS_TOKEN_CACHE_TTL", "3000")),
    # Foydalanuvchi maksimum nechta karta saqlay oladi
    "MAX_SAVED_CARDS": int(os.getenv("ATMOS_MAX_SAVED_CARDS", "5")),
}

# Atmos ASL (payout — doctor balansidan karta'ga avtomatik o'tkazma)
# Acquiring (ATMOS dict tepada) bilan alohida credential'lar va base URL.
# Acquiring: apigw.atmos.uz · ASL: apigw.atmos.uz/out/1.0.0/asl
ATMOS_ASL = {
    "USERNAME": os.getenv("ATMOS_ASL_USERNAME", ""),
    "PASSWORD": os.getenv("ATMOS_ASL_PASSWORD", ""),
    "BASE_URL": os.getenv(
        "ATMOS_ASL_BASE_URL", "https://apigw.atmos.uz/out/1.0.0/asl"
    ),
    # ATMOS ASL /token expires_in=3600 beradi → 50min cache (10min buffer).
    "TOKEN_CACHE_TTL": int(os.getenv("ATMOS_ASL_TOKEN_CACHE_TTL", "3000")),
    # Polling: PENDING (state=13) bo'lganda nechta marta qayta urinish (Celery retry).
    "POLL_MAX_RETRIES": int(os.getenv("ATMOS_ASL_POLL_MAX_RETRIES", "120")),
    "POLL_COUNTDOWN_SEC": int(os.getenv("ATMOS_ASL_POLL_COUNTDOWN_SEC", "15")),
    # Minimal depozit threshold (so'mda) — pastga tushsa adminga ogohlantirish
    "MIN_DEPOSIT_WARN_SUM": int(os.getenv("ATMOS_ASL_MIN_DEPOSIT_WARN_SUM", "1000000")),
}

# Celery
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 daqiqa max
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 daqiqada warning
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


# Dedicated worker: docker-compose `celery-transcode` (-Q transcode).
CELERY_TASK_ROUTES = {
    "chat.transcode_voice_message": {"queue": "transcode"},
}

# Celery Beat — davriy tasklar
CELERY_BEAT_SCHEDULE = {
    "check-daily-treatments": {
        "task": "treatment.check_daily_treatments",
        "schedule": 60.0,  # har daqiqa — dori slotlarini aniq vaqtda eslatish (per-slot dedup)
    },
    "cleanup-deleted-chat-messages": {
        "task": "chat.cleanup_old_deleted_messages",
        "schedule": 86400.0,  # har kuni
    },
    "notify-expired-subscriptions": {
        "task": "payments.notify_expired_subscriptions",
        "schedule": 86400.0,  # har kuni
    },
    # Webhook miss bo'lganda paytechuz Transaction bilan solishtirib PENDING
    # Payment'larni avtomatik COMPLETED yoki CANCELLED ga o'tkazadi.
    "reconcile-pending-payments": {
        "task": "payments.reconcile_pending_payments",
        "schedule": 1800.0,  # har 30 daqiqada
    },
    # 24 soatdan eski PENDING Payment'larni avtomatik CANCELLED qiladi
    "expire-stale-payments": {
        "task": "payments.expire_stale_payments",
        "schedule": 3600.0,  # har 1 soatda
    },
    # To'lanmagan konsultatsiyalarni (pending_payment, TTL o'tgan) expired qilib
    # slotni bo'shatadi — boshqa bemor band qila oladi.
    "expire-unpaid-consultations": {
        "task": "meetings.expire_unpaid_consultations",
        "schedule": 300.0,  # har 5 daqiqada
    },
    # Approved appointmentlarni vaqti + 2 soat o'tgach COMPLETED ga o'tkazadi.
    # Doctor "complete" bosishni unutsa, patient review yozolishi uchun.
    "auto-complete-appointments": {
        "task": "meetings.auto_complete_appointments",
        "schedule": 1800.0,  # har 30 daqiqada
    },
    # Confirmed konsultatsiyalarni tugash vaqti + grace o'tgach COMPLETED ga
    # o'tkazadi (Consultation Appointment'dan alohida model — auto_complete_appointments
    # uni qamramaydi; aks holda abadiy `confirmed` qolardi).
    "auto-complete-consultations": {
        "task": "meetings.auto_complete_consultations",
        "schedule": 1800.0,  # har 30 daqiqada
    },
    # PayoutRequest sub_status: submitted → in_review (UI uchun).
    "auto-mark-payouts-in-review": {
        "task": "payments.auto_mark_payouts_in_review",
        "schedule": 900.0,  # har 15 daqiqada
    },
    # ASL'ga yetib bormagan pending payout'larni qayta urinish
    "retry-pending-asl-payouts": {
        "task": "payments.retry_pending_asl_payouts",
        "schedule": 300.0,  # har 5 daqiqada
    },
    "translate-missing-catalogs": {
        "task": "core.translate_missing_catalogs",
        "schedule": 86400.0,  # har kuni
    },
    # Analiz deadline'i 24 soat qolganda bemorga eslatma.
    "check-analysis-deadlines": {
        "task": "medical.check_analysis_deadlines",
        "schedule": 3600.0,  # har 1 soatda
    },
    # Deadline o'tib ketgan analizlar — bemorga "muddati o'tdi" xabari.
    "expire-overdue-analyses": {
        "task": "medical.expire_overdue_analyses",
        "schedule": 3600.0,  # har 1 soatda
    },
    # ATMOS ASL — kunlik sverka: bizning PayoutRequest'lar va ATMOS /list mosligini
    "atmos-asl-reconcile": {
        "task": "payments.atmos_asl_reconcile",
        "schedule": 86400.0,  # har kuni
    },
    # ATMOS ASL — depozit past bo'lsa ROOT_ADMIN'ga signal.
    "atmos-asl-deposit-alert": {
        "task": "payments.atmos_asl_deposit_alert",
        "schedule": 21600.0,  # har 6 soatda (kunda 4 marta tekshiriladi, 2 marta xabar)
    },
    # Kunlik AI health report (DOCTOR uchun) — har ertalab 06:00 Asia/Tashkent.
    "daily-ai-health-report": {
        "task": "health_ai.generate_daily_reports",
        "schedule": crontab(hour=6, minute=0),
    },
    # Kunlik AI tracking (BEMOR-markazli) — 06:30 (health_ai bilan stagger).
    "daily-ai-tracking": {
        "task": "tracking_ai.generate_daily_tracking",
        "schedule": crontab(hour=6, minute=30),
    },
}

# Redis Cache
if CELERY_BROKER_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": CELERY_BROKER_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
            "KEY_PREFIX": "mediik",
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

# Sentry — production error tracking + logs
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
# TESTING'da Sentry init qilinmaydi — local test run'lar (manage.py test) DEBUG=False
# ishlatadi va aks holda "production" xato bo'lib Sentry'ni ifloslaydi.
if SENTRY_DSN and not TESTING:
    from django.core.exceptions import DisallowedHost, SuspiciousOperation
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,  # 10% performance monitoring
        profiles_sample_rate=0.1,
        send_default_pii=False,
        environment="production" if not DEBUG else "development",
        # Bot scanner shovqinlarini ignore qilamiz:
        #   DisallowedHost — random HTTP_HOST header'lar bilan scan
        #   SuspiciousOperation — boshqa security-related lekin biz'da
        #     handle qilinmagan request muammolari (ko'pchiligi noise)
        ignore_errors=[
            SystemExit,
            KeyboardInterrupt,
            DisallowedHost,
            SuspiciousOperation,
        ],
        # Sentry Logs (https://mediik.sentry.io/explore/logs/)
        # INFO va undan yuqori darajadagi Python loglarini Sentry'ga yuboradi
        _experiments={"enable_logs": True},
        integrations=[
            LoggingIntegration(
                level=logging.INFO,         # breadcrumb darajasi
                event_level=logging.ERROR,  # alohida event sifatida yuboriladigan daraja
                sentry_logs_level=logging.INFO,  # Sentry Logs'ga yuboriladigan daraja
            ),
        ],
    )

# Django Channels (WebSocket)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [CELERY_BROKER_URL or "redis://localhost:6379/0"],
        },
    }
    if CELERY_BROKER_URL
    else {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# DigitalOcean Spaces (S3-compatible)
DO_SPACES_KEY = os.getenv("DO_SPACES_KEY", "")
DO_SPACES_SECRET = os.getenv("DO_SPACES_SECRET", "")
DO_SPACES_BUCKET = os.getenv("DO_SPACES_BUCKET", "mediik")
DO_SPACES_REGION = os.getenv("DO_SPACES_REGION", "ams3")
DO_SPACES_ENDPOINT = os.getenv(
    "DO_SPACES_ENDPOINT", "https://ams3.digitaloceanspaces.com"
)

# Bunny CDN
BUNNY_CDN_URL = os.getenv("BUNNY_CDN_URL", "https://mediik.b-cdn.net")
BUNNY_TOKEN_KEY = os.getenv("BUNNY_TOKEN_KEY", "")

# Chat settings
CHAT_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
CHAT_ALLOWED_FILE_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/wav",
    # Web MediaRecorder (Chrome/Firefox/Edge) ovozli xabar — webm/opus.
    # Frontend codecs'ni olib tashlaydi → "audio/webm" keladi.
    "audio/webm",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]

REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = [
    "rest_framework.throttling.AnonRateThrottle",
    "rest_framework.throttling.UserRateThrottle",
]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "30/minute",
    "user": "120/minute",
    # Audit C4 — referral code endpoint enumeration himoyasi.
    # Hujumchi 8-belgili kodlar bo'yicha bruteforce qilib doctor/seller PII'sini
    # chiqarib olishi mumkin. Per-IP juda qisqa.
    "referral_lookup": "10/minute",
    # Qo'ng'iroq boshlash — push/ring spam (harassment, batareya) oldini olish.
    "call_start": "10/minute",
}

# Logging
# ---------------------------------------------------------------------------
# LOG_FORMAT:
#   "json"  — strukturli JSON (Better Stack uchun, productionda default)
#   "plain" — o'qiladigan matn (lokal runserver uchun, DEBUG=True da default)
# SERVICE_NAME:
#   Har Docker service alohida qiymat beradi (web/bot/celery/beat/flower).
#   Better Stack shu maydon bo'yicha kim qanday log yozganini ajratadi.
LOG_FORMAT = os.getenv("LOG_FORMAT", "plain" if DEBUG else "json")
SERVICE_NAME = os.getenv("SERVICE_NAME", "web")
LOG_ENVIRONMENT = "development" if DEBUG else "production"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
        "json": {
            "()": "core.logging.JsonFormatter",
            "service": SERVICE_NAME,
            "environment": LOG_ENVIRONMENT,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "data" / "mediik.log",
            "formatter": LOG_FORMAT,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file"],
            "level": "WARNING",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "core.tasks": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "mediik": {  # umumiy app namespace — loggers = logging.getLogger("mediik.xxx")
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "mediik.request": {  # access log (RequestContextMiddleware yozadi)
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


# --- Gemini AI (Diet AI uchun) ---
# 5 ta API key — rate limit'dan qochish uchun rotation ishlatiladi
GEMINI_API_KEY_1 = os.getenv("GEMINI_API_KEY_1", "")
GEMINI_API_KEY_2 = os.getenv("GEMINI_API_KEY_2", "")
GEMINI_API_KEY_3 = os.getenv("GEMINI_API_KEY_3", "")
GEMINI_API_KEY_4 = os.getenv("GEMINI_API_KEY_4", "")
GEMINI_API_KEY_5 = os.getenv("GEMINI_API_KEY_5", "")
# Fallback (eski single key)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Vertex AI (Gemini) — $300/postpay, prepay devori yo'q ---
# GEMINI_USE_VERTEX=true bo'lsa: text/rasm/audio generatsiya Vertex orqali (ADC auth —
# GEMINI_API_KEY_* o'rniga service account / gcloud). Voice AI (ephemeral token) alohida
# — u hozircha AI Studio'da qoladi. Flag=false bo'lsa hech nima o'zgarmaydi.
GEMINI_USE_VERTEX = os.getenv("GEMINI_USE_VERTEX", "false").lower() == "true"
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GEMINI_VERTEX_LOCATION = os.getenv("GEMINI_VERTEX_LOCATION", "us-central1")

# --- Voice AI (Gemini Live) ---
# VOICE_USE_VERTEX=true  → Vertex client-direct: backend qisqa OAuth token + config beradi,
#                          mobil to'g'ridan Vertex Live'ga ulanadi ($300, prepay devorisiz).
# VOICE_USE_VERTEX=false → AI Studio ephemeral token (config token ichiga baked).
VOICE_USE_VERTEX = os.getenv("VOICE_USE_VERTEX", "false").lower() == "true"
VOICE_LIVE_MODEL = os.getenv("VOICE_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
VOICE_VERTEX_LIVE_MODEL = os.getenv("VOICE_VERTEX_LIVE_MODEL", "gemini-live-2.5-flash-native-audio")
VOICE_VERTEX_LOCATION = os.getenv("VOICE_VERTEX_LOCATION", "us-central1")

# --- LiveKit (video call) ---
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
