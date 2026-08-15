# Sog'liq Navigator — Backend

> NEXUS30 hackathoni, HealthTech treki ("Kasallik bo'yicha AI navigator" keysi).
> Bemorga tashxisdan KEYIN yo'l ko'rsatadigan platforma: shifokor, AI va oila
> a'zosi bemorni birgalikda kuzatib boradi.

Jamoaning Mediik platformasi asosida qurilgan — hackathon uchun klinika (B2B)
va braslet modullari olib tashlanib, o'rniga **oila a'zosi kuzatuvi** va
**Tracking AI** qo'shilgan.

## Asosiy imkoniyatlar

| Modul | Nima qiladi |
|-------|-------------|
| Auth | Telegram OTP / SMS + JWT (patient/doctor/admin scope) |
| Doctors | Shifokor profili, jadval, slotlar, bemor bog'lanishlari |
| Meetings | Qabulga yozilish, LiveKit video qo'ng'iroqlar |
| Treatment | Muolaja rejasi, eslatmalar (Telegram+push), bajarilish statistikasi |
| Medical | Tibbiy karta, kasallik holatlari, shifokor yozuvlari, tahlillar |
| Health packages | Kunlik kayfiyat + qo'lda kiritiladigan salomatlik ko'rsatkichlari |
| Chat | Doctor↔Patient real-time chat (WebSocket), AI-gatekeeper |
| Diet AI | Gemini: ovqat tahlili (foto/matn), kaloriya kuzatuvi, AI suhbat |
| Health AI | Shifokor uchun kunlik AI hisobot (bemor dinamikasi) |
| **Tracking AI** ⭐ | Bemor-markazli kunlik AI kuzatuv: xulosa, o'zgarishlar, tavsiyalar; kritik holatda bemor + shifokor + oila a'zosiga push |
| **Family** ⭐ | Oila a'zosi bemorni kuzatadi: taklif → qabul → read-only kunlik hisobot |
| Notifications | In-app feed + FCM/APNs push (app_scope bilan) |
| Voice AI | Gemini Live — ovozli suhbat (server orqali o'tmaydi) |

⭐ — hackathon uchun yangi qo'shilgan modullar. API namunalari:
[FAMILY_TRACKING_API.md](FAMILY_TRACKING_API.md).

## Demo cheklovlari

- **To'lovlar o'chirilgan** (`PAYMENTS_ENABLED=False` default): to'lov boshlaydigan
  endpointlar `503 + {"code": "payments_demo_mode", "detail": "Bu demo versiya —
  to'lovlar hozircha ishlamaydi..."}` qaytaradi. O'qish endpointlari ishlaydi.
- AI hech qachon tashxis qo'ymaydi va dori tavsiya qilmaydi — prompt darajasida
  qattiq qoidalar, kritik holatda 103 ga yo'naltiradi.

## Texnologiyalar

Django 5 + DRF + drf-spectacular · Celery + Redis · Django Channels ·
LiveKit · Firebase FCM + APNs · Google Gemini · Payme/Click/Uzum (paytechuz) ·
PostgreSQL (prod) / SQLite (dev)

## Ishga tushirish

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # kalitlarni to'ldiring (minimal: SECRET_KEY, GEMINI_API_KEY_1)

python manage.py migrate
python manage.py runserver
```

- Swagger: `http://localhost:8000/docs/`
- Telegram bot (ixtiyoriy, alohida terminal): `python manage.py run_bot`
- Redis'siz lokal ishlash: `.env`dagi `CELERY_BROKER_URL` va
  `CELERY_RESULT_BACKEND`ni bo'sh qoldiring (cache LocMem'ga tushadi).

## Testlar

```bash
DJANGO_SETTINGS_MODULE=config.test_settings python manage.py test tests --noinput
```

## Tuzilish

```
app/
├── auth/ users/ doctors/ meetings/     # identity + qabul
├── treatment/ medical/ health_packages/ # bemor kuzatuvi (ma'lumotlar)
├── family/                              # ⭐ oila a'zosi kuzatuvi
├── tracking_ai/                         # ⭐ AI kuzatuvchi (beat 06:30)
├── diet_ai/ health_ai/ voice_ai/        # boshqa AI modullari
├── chat/ notifications/ payments/ ...
config/    # settings, urls, celery
core/      # permissions, exceptions, i18n, BaseTask
services/  # gemini, telegram, livekit, firebase, storage
tests/     # test suite
```

Kod yozish qoidalari va arxitektura tafsilotlari: [CLAUDE.md](CLAUDE.md).
