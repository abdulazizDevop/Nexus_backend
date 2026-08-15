"""Test uchun settings — Redis o'rniga locmem cache, throttle o'chirilgan"""
from config.settings import *  # noqa

# Test da Redis kerak emas
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Test da throttle o'chirish
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}

# Celery sinxron ishlaydi test da
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Sentry o'chirish
SENTRY_DSN = None
