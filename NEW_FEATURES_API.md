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

## AI Navigator — `/api/v1/navigator/`

**To'liq kontrakt: [docs/ai_navigator_api_contract.md](docs/ai_navigator_api_contract.md)**
(mobil jamoa bilan shartnoma — request/response'lar aynan o'sha hujjatdagidek).
Backend to'liq implementatsiya qildi:

| Endpoint | Holat | Izoh |
|----------|-------|------|
| `GET /navigator/diagnoses/` | ✅ | Paginatsiyalangan ro'yxat + roadmap_progress |
| `GET /navigator/diagnoses/{id}/` | ✅ | Tashxis + to'liq roadmap (what_to_watch, red_flags) |
| `GET /navigator/roadmap/active/` | ✅ 🔴 | Home ekrani; aktiv yo'q → `{"diagnosis": null}` |
| `POST /navigator/steps/{id}/complete/` | ✅ 🔴 | done + keyingi locked → current, `unlocked_step_ids` |
| `POST /navigator/chat/` | ✅ 🟠 | Kontekstni backend yig'adi (§11: ism/telefon uzatilmaydi), kunlik limit 30 |
| `POST /navigator/diagnoses/from-image/` | ✅ 🟠 | multipart rasm → Gemini vision → tashxis + roadmap + `extraction`; rasm SAQLANMAYDI |
| `POST /navigator/diagnoses/` | ✅ | Qo'lda kiritish → AI roadmap quradi (dori qadamsiz — keys §9) |
| `POST /navigator/triage/` | ✅ 🟡 | Simptom → urgency + mutaxassisliklar + platformadagi shifokorlar |

Model: tashxis = `MedicalCondition` (+`icd10`, `plain_explanation`, `is_active`,
`source`, `what_to_watch`, `red_flags`, `extraction`), qadamlar = `RoadmapStep`
(`type`: medication/analysis/consultation/lifestyle/checkup/education;
`status`: done/current/locked/skipped — ketma-ket ochiladi; `payload` tur-ga
bog'liq, kontrakt §2). Xatolar kontrakt §10 formatida:
`{"detail": "machine_code", "message": "matn"}` (`document_unreadable` 422,
`ai_unavailable` 503, `daily_limit_exceeded` 429).

AI qoidalari: tashxis QO'YMAYDI (tayyor tashxisdan keyin yo'naltiradi), manual
tashxisda dori qadami YARATMAYDI (faqat hujjatda yozilgan dorilar from-image'da),
kontekstga ism/telefon uzatilmaydi.

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
