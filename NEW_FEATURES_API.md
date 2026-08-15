# Yangi funksiyalar API (Postman namunalari)

Mediik'da YO'Q, Sog'liq Navigator uchun yangi qo'shilgan funksiyalar:

| Bo'lim | Prefix |
|--------|--------|
| Family — oila a'zosi kuzatuvi | `/api/v1/family/` |
| Tracking AI — AI kuzatuvchi | `/api/v1/tracking-ai/` |
| Retsept skan (AI vision) | `/api/v1/treatments/prescription/` |
| Navigator yo'l xaritasi | `/api/v1/medical/roadmap/` |
| Voice AI + kuzatuv konteksti | (mavjud `/api/v1/voice/` kengaytmasi) |
| To'lov demo-rejimi | barcha to'lov endpointlari |

Barcha so'rovlarda: `Authorization: Bearer <access_token>` (webhook'lardan tashqari).

---

## Family — bemor tomoni (patient scope)

### 1. A'zoni taklif qilish

```
POST /api/v1/family/members/invite/
Content-Type: application/json

{ "phone": "998901112233", "relation": "child" }
```

`relation`: `child` | `parent` | `spouse` | `sibling` | `other`

**201 Created** (yangi taklif) / **200 OK** (qayta taklif):
```json
{
  "id": 4, "member": 12, "member_name": "Aziza Karimova",
  "member_phone": "998901112233",
  "relation": "child", "relation_display": "Farzand",
  "status": "pending", "status_display": "Kutilmoqda",
  "responded_at": null, "created_at": "2026-08-15T14:20:00+05:00"
}
```

**404** — raqam ro'yxatdan o'tmagan; **400** — o'zini qo'shish yoki allaqachon ACCEPTED.
A'zoga push boradi: `type=family_invite`, `app_scope=patient`.

### 2. A'zolar ro'yxati

```
GET /api/v1/family/members/
```
**200** — yuqoridagi obyektlar massivi (REVOKED'lar chiqmaydi).

### 3. A'zoni chiqarish

```
DELETE /api/v1/family/members/4/
```
**204 No Content** — status `revoked` bo'ladi, a'zo kirish huquqini yo'qotadi.

---

## Family — a'zo tomoni (patient scope)

### 4. Menga kelgan takliflar

```
GET /api/v1/family/me/invitations/
```
**200**:
```json
[{
  "id": 4, "patient": 7, "patient_profile_id": 7,
  "patient_name": "Karim Toshmatov", "patient_phone": "998907654321",
  "relation": "child", "relation_display": "Farzand",
  "status": "pending", "status_display": "Kutilmoqda",
  "responded_at": null, "created_at": "2026-08-15T14:20:00+05:00"
}]
```

### 5. Qabul qilish / rad etish

```
POST /api/v1/family/me/4/accept/
POST /api/v1/family/me/4/decline/
```
**200** — yangilangan link obyekti. Bemorga push: `family_accepted` / `family_declined`.
**404** — taklif topilmadi yoki allaqachon javob berilgan.

### 6. Men kuzatayotgan bemorlar

```
GET /api/v1/family/me/patients/
```
**200** — ACCEPTED linklar massivi (4-banddagi format).

### 7. Bemorning kunlik hisoboti (faqat o'qish)

```
GET /api/v1/family/patients/7/daily-report/?date=2026-08-15
```
**200**:
```json
{
  "date": "2026-08-15",
  "patient_id": 7,
  "patient_name": "Karim Toshmatov",
  "checkup": { "status": "good", "note": "" },
  "indicators": [
    { "id": 91, "metric": "blood_pressure", "display_value": "128/84", "recorded_at": "..." }
  ],
  "treatments": [
    { "id": 3, "title": "Ertalabki dori", "type": "medication", "completed": 1, "total": 2 }
  ],
  "completion_percent": 50,
  "ai_report": { "summary": "...", "severity": "normal", "period_start": "2026-08-14" }
}
```
**403** — ACCEPTED bog'lanish yo'q. `date` bermasa — bugun.

---

## Tracking AI

### 8. O'z hisobotlarim (bemor)

```
GET /api/v1/tracking-ai/reports/
```
**200** (paginatsiyalangan):
```json
{
  "count": 2, "next": null, "previous": null,
  "results": [{
    "id": 15, "patient": 7, "patient_profile": 7, "patient_name": "Karim Toshmatov",
    "period_start": "2026-08-14", "period_end": "2026-08-14",
    "summary": "Kecha muolajalaringizning 80% ini bajardingiz...",
    "detected_changes": [
      { "title": "Qon bosimi", "description": "Kechagiga nisbatan barqaror", "severity": "info" }
    ],
    "recommendations": ["Kechki o'lchovni unutmang."],
    "adherence_percent": 80,
    "severity": "normal", "severity_display": "Normal",
    "seen_at": null, "created_at": "2026-08-15T06:30:12+05:00"
  }]
}
```

### 9. Oxirgi hisobot / o'qildi belgisi

```
GET  /api/v1/tracking-ai/reports/latest/          → 200 yoki 404 (hali yo'q)
POST /api/v1/tracking-ai/reports/15/seen/         → 200 (seen_at to'ldiriladi)
```

### 10. Hozir yaratish (on-demand, bugungi kun)

```
POST /api/v1/tracking-ai/reports/generate/
```
**201** — yangi/yangilangan hisobot (8-band formati).
**502** — Gemini xatosi; **400** — yaratib bo'lmadi (masalan profil yo'q).

### 11. Bemor hisobotlari (shifokor yoki oila a'zosi)

```
GET /api/v1/tracking-ai/reports/by-patient/7/
```
Ruxsat: bemorning o'zi, ACCEPTED `DoctorPatient` shifokori (doctor scope) yoki
ACCEPTED `FamilyLink` a'zosi (patient scope). Aks holda **403**.

---

## Fon jarayoni

- Celery beat: har kuni **06:30** (`tracking_ai.generate_daily_tracking`) — kecha
  faollik ko'rsatgan har bir bemor uchun hisobot (idempotent, activity-filter bilan).
- `severity=critical` bo'lsa push: bemor (`patient`), ACCEPTED shifokorlar (`doctor`),
  ACCEPTED oila a'zolari (`patient`) — `type=tracking_alert`.
- AI qoidalari (prompt darajasida qattiq): tashxis qo'ymaydi, dori/doza tavsiya
  qilmaydi, kritik holatda 103/shifokorga yo'naltiradi.

---

## Retsept skan (AI) — `/api/v1/treatments/prescription/`

Tashxis/retsept qog'ozi rasmga olinadi → Gemini vision o'qiydi → bemor
TASDIQLAYDI → tasdiqlangan bandlar muolajalarga (Treatment) qo'shiladi.
AI qog'ozda yozilmagan narsani qo'shmaydi; o'qib bo'lmagan joylar `warnings`da.

### 1. Upload URL

```
POST /api/v1/treatments/prescription/upload-url/
{ "file_type": "image/jpeg" }
```
**200**: `{ "upload_url": "...", "image_key": "prescriptions/7/a1b2c3d4.jpg", "expires_in": 900 }`
Keyin client `PUT {upload_url}` bilan rasmni yuklaydi.

### 2. AI tahlil

```
POST /api/v1/treatments/prescription/analyze/
{ "image_key": "prescriptions/7/a1b2c3d4.jpg" }
```
**201** — `status="pending_review"` skan:
```json
{
  "id": 3, "status": "pending_review",
  "summary": "Qog'ozda 2 ta dori va ichish tartibi yozilgan.",
  "ai_items": [
    { "title": "Amlodipin 5mg", "type": "medication", "dosage": "1 tabletka",
      "times": ["08:00"], "repeat": "daily", "duration_days": 30,
      "notes": "Ertalab, ovqatdan keyin", "source_text": "Amlodipin 5mg 1x1 ertalab" }
  ],
  "ai_warnings": ["'kuniga 2 mahal' 08:00/20:00 deb taqsimlandi."]
}
```
**400** — retsept aniqlanmadi / begona image_key / 10MB+; **502** — AI xatosi.

### 3. Tasdiqlash (bemor tahrir qilishi mumkin)

```
POST /api/v1/treatments/prescription/3/confirm/
{ "items": [
    { "title": "Amlodipin 5mg", "type": "medication", "dosage": "1 tabletka",
      "times": ["08:00"], "repeat": "daily", "duration_days": 30, "notes": "Ertalab" }
] }
```
**201** — `{"scan": {...status: "confirmed"...}, "created_treatments": [...]}`.
Har item `Treatment` bo'ladi (self-added, `created_by=null`), eslatmalar avtomatik ishlaydi.
**400** — skan allaqachon ko'rib chiqilgan.

### 4. Rad etish / ro'yxat

```
POST /api/v1/treatments/prescription/3/discard/   → 200 (status=discarded)
GET  /api/v1/treatments/prescription/             → oxirgi 20 skan
GET  /api/v1/treatments/prescription/3/           → bitta skan
```

## Voice AI + kuzatuv

Ovozli yordamchi kontekstiga bemorning kunlik kuzatuvi qo'shildi: muolaja
intizomi, ko'rsatkichlar, kayfiyat va oxirgi AI kuzatuv hisoboti (2 kundan
eski bo'lmasa). Bemor "ahvolim qanday?" desa yordamchi shu raqamlar asosida
gapiradi; hisobotda JIDDIY holat bo'lsa shifokorga murojaatni eslatadi.

---

## Navigator yo'l xaritasi — `/api/v1/medical/roadmap/`

Tashxisdan keyingi qadam-baqadam yo'l xaritasi (konseptdagi S3/S4 ekranlar
backend'i). Tashxis `MedicalCondition`da (`icd10`, `plain_explanation`,
`is_active` maydonlari qo'shildi), qadamlar `RoadmapStep`da.

### 1. O'rnatish (tashxis + qadamlar bitta so'rovda)

```
POST /api/v1/medical/roadmap/setup/
{
  "condition": {
    "name": "Arterial gipertoniya", "icd10": "I10", "type": "chronic",
    "plain_explanation": "Qon bosimining doimiy yuqori bo'lishi..."
  },
  "steps": [
    { "period": "first_week", "order": 1, "title": "Kardiolog qabuliga yoziling",
      "specialist": "Kardiolog", "description": "Bosim yozuvlaringizni olib boring." },
    { "period": "ongoing", "order": 1, "title": "Kunlik bosim nazorati" }
  ]
}
```
`period`: `first_week` | `first_month` | `ongoing` (doimiy = odat, yopilmaydi).
**201** — to'liq roadmap payload (2-band formati). Avvalgi aktiv tashxis
avtomatik deaktiv bo'ladi (qadamlari tarixda qoladi).

### 2. Aktiv yo'l xaritasi

```
GET /api/v1/medical/roadmap/active/
```
**200**:
```json
{
  "condition": { "id": 5, "name": "Arterial gipertoniya", "icd10": "I10",
                 "plain_explanation": "...", "is_active": true },
  "periods": [
    { "period": "first_week", "period_label": "Birinchi hafta",
      "steps": [ { "id": 11, "title": "Kardiolog qabuliga yoziling",
                   "specialist": "Kardiolog", "status": "pending",
                   "is_habit": false, "order": 1 } ] },
    { "period": "first_month", "period_label": "Birinchi oy", "steps": [] },
    { "period": "ongoing", "period_label": "Doimiy", "steps": [] }
  ],
  "progress": { "completed": 0, "total": 3, "percent": 0, "habits": 1 }
}
```
**404** — aktiv tashxis yo'q (avval setup qilinadi).

### 3. Qadamni bajarish / bekor qilish

```
POST /api/v1/medical/roadmap/steps/11/complete/    → 200 {step, progress}
POST /api/v1/medical/roadmap/steps/11/uncomplete/  → 200 {step, progress}
```
Idempotent. `progress` faqat belgilanadigan qadamlarni sanaydi (odatlar
`habits` sonida alohida). **400** — doimiy (odat) qadamni yopishga urinish.

---

## To'lov demo-rejimi

`PAYMENTS_ENABLED=False` (default) bo'lganda to'lov BOSHLAYDIGAN endpointlarga
yozuv so'rovi:

```
POST /api/v1/payments/pro/subscribe/  (yoki topup/, atmos/*, offline/*,
                                       doctor-tariffs/{id}/purchase/, webhook/*)
```
**503**:
```json
{
  "detail": "Bu demo versiya — to'lovlar hozircha ishlamaydi. Barcha imkoniyatlar to'lovsiz ochiq.",
  "code": "payments_demo_mode"
}
```
O'qish endpointlari (planlar, tariflar, balans) odatdagidek ishlaydi.
