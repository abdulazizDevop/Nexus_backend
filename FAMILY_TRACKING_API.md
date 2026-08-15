# Family + Tracking AI API (Postman namunalari)

Sog'liq Navigator backend'iga qo'shilgan ikki yangi modul:
- **`/api/v1/family/`** — oila a'zosi bemorni kuzatadi (taklif → qabul → o'qish huquqi);
- **`/api/v1/tracking-ai/`** — AI bemorni kunlik kuzatib boradi (shifokor va oila bilan birga).

Barcha so'rovlarda: `Authorization: Bearer <access_token>`.

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
