"""Diet AI (Gemini) models.

4 ta model:
    - DietConversation   — mavzu bo'yicha suhbat (Telegram'dek alohida chatlar)
    - DietMessage        — suhbat ichidagi har bir xabar (user/assistant)
    - DietRestriction    — doctor bemor uchun qo'ygan cheklov ("shakarsiz" va h.k.)
    - DietDailyUsage     — kunlik limit hisoblash (bepul userlar uchun 10/day)
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from app.doctors.models import DoctorProfile
from app.users.models import Patient

def _patient_profile_id_for(user_id):
    """user_id -> Patient.id (yozuv-mirror auto-fill uchun), qisqa cache bilan.

    Har Diet yozuvi saqlanganda `Patient.objects.get_or_create` chaqirilardi —
    bitta so'rovda bir necha yozuv yaratilganda (masalan confirm-calories:
    entry + message + usage) bu takroriy SELECT (N+1) berardi. Patient User bilan
    birga avto-yaratiladi va O'ZGARMAYDI, shuning uchun id'ni qisqa keshlash
    xavfsiz (kesh yo'q bo'lsa odatdagi get_or_create).
    """
    from django.core.cache import cache

    key = f"patient_profile_id:{user_id}"
    pid = cache.get(key)
    if pid:
        return pid
    profile, _ = Patient.objects.get_or_create(user_id=user_id)
    cache.set(key, profile.id, 3600)
    return profile.id


# Rasmi bor xabar: image_key NULL ham, bo'sh string ham emas.
