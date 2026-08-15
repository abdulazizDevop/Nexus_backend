import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mediik")

# settings.py dan CELERY_ prefiksi bilan o'qiydi
app.config_from_object("django.conf:settings", namespace="CELERY")

# Barcha app lardagi tasks.py fayllarni avtomatik topadi
app.autodiscover_tasks()
