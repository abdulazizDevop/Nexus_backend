# AI Navigator — API kontrakti

> **Keys:** Yandex — «Kasallik bo'yicha AI navigator»
> **Maqsad:** tashxis allaqachon aniqlangan bemorga keyingi harakatlar ketma-ketligini
> tizimli va tushunarli tarzda ko'rsatish. Tizim **tashxis qo'ymaydi** — faqat mavjud
> tashxisdan keyin yo'naltiradi (keys §9 cheklovi).

Ushbu hujjat **shartnoma**: backend shu bo'yicha yozadi, Flutter shu bo'yicha o'qiydi.
Mobil tomonda bir xil kontraktli `NavigatorMockDataSource` bor — backend kechiksa ham
demo ishlaydi, tayyor bo'lganda `injection.dart` da bitta qator almashadi (CLAUDE.md §15).

Base URL: `ApiConstants.baseUrl` (`api.dev.mediik.uz` / `api.prod.mediik.uz`).
Auth: `Authorization: Bearer <access_token>` — barcha endpointlarda majburiy.
Til: `Accept-Language: uz | ru | cyr` (ApiClient avtomatik qo'yadi).

---

## 0. Umumiy tiplar

### `StepType` — qadam turi

| Qiymat | Ma'nosi | Mobil harakati |
|--------|---------|----------------|
| `medication` | Dori qabul qilish | Muolaja (to-do) ga avtomatik qo'shiladi |
| `analysis` | Analiz topshirish | Analizlar bo'limiga deep-link |
| `consultation` | Shifokorga murojaat | Marketplace'ni `specialty` filtri bilan ochadi |
| `lifestyle` | Turmush tarzi / parhez | Salomatlik → Parhez bo'limiga |
| `checkup` | Nazorat ko'rigi | Uchrashuv yozilishi |
| `education` | Tushuntirish / o'qish | Matn sheet'i ochiladi |

### `StepStatus` — qadam holati

| Qiymat | Ma'nosi |
|--------|---------|
| `done` | Bajarilgan |
| `current` | Hozir bajarilishi kerak |
| `locked` | Oldingi qadamlar tugamaguncha yopiq |
| `skipped` | O'tkazib yuborilgan (muddati o'tgan) |

### `DiagnosisSource` — tashxis qayerdan keldi

| Qiymat | Ma'nosi |
|--------|---------|
| `doctor` | Platformadagi shifokor qo'ydi |
| `document` | Tashxis qog'ozi rasmga olinib AI o'qidi |
| `manual` | Bemor o'zi kiritdi |
| `integration` | Tashqi klinika tizimidan integratsiya orqali |

---

## 1. `GET /navigator/diagnoses/`

Bemorning barcha tashxislari. `PageNumberPagination` (CLAUDE.md §21).

**Javob 200:**

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 41,
      "title": "Gastroezofageal reflyuks kasalligi (GERD)",
      "icd10": "K21.0",
      "source": "doctor",
      "is_active": true,
      "diagnosed_at": "2026-08-10",
      "doctor": {
        "id": 12,
        "full_name": "Aziza Karimova",
        "specialty": "Gastroenterolog"
      },
      "roadmap_progress": {
        "total_steps": 8,
        "done_steps": 3,
        "percent": 37
      }
    }
  ]
}
```

`doctor` — `null` bo'lishi mumkin (`source` = `document` / `manual`).

---

## 2. `GET /navigator/diagnoses/{id}/`

Bitta tashxis + **to'liq roadmap**. Bu keysning markaziy endpointi.

**Javob 200:**

```json
{
  "id": 41,
  "title": "Gastroezofageal reflyuks kasalligi (GERD)",
  "icd10": "K21.0",
  "source": "doctor",
  "is_active": true,
  "diagnosed_at": "2026-08-10",

  "plain_explanation": "Oshqozon kislotasi qizilo'ngachga qaytib chiqadi. Bu jiddiy emas, lekin davolanmasa qizilo'ngach shilliq qavatini shikastlaydi. Ko'p hollarda dori va ovqatlanish tartibi bilan nazorat qilinadi.",

  "what_to_watch": [
    "Ovqatdan keyin ko'krak orqasida achishish kuchaysa",
    "Yutishda og'riq paydo bo'lsa",
    "Vazn sababsiz kamaysa"
  ],

  "red_flags": [
    {
      "text": "Qon aralash qusish yoki qora najas",
      "action": "Zudlik bilan tez yordam chaqiring",
      "severity": "emergency"
    }
  ],

  "roadmap": {
    "id": 77,
    "total_steps": 8,
    "done_steps": 3,
    "percent": 37,
    "steps": [
      {
        "id": 501,
        "order": 1,
        "type": "education",
        "status": "done",
        "title": "Kasallik haqida tushuncha",
        "description": "GERD nima va nima uchun paydo bo'ladi.",
        "body": "To'liq matn — sheet ichida ko'rsatiladi.",
        "due_date": null,
        "completed_at": "2026-08-10T14:20:00Z",
        "payload": null
      },
      {
        "id": 502,
        "order": 2,
        "type": "medication",
        "status": "done",
        "title": "Omeprazol 20 mg",
        "description": "14 kun davomida, ertalab nahorga.",
        "due_date": "2026-08-24",
        "completed_at": null,
        "payload": {
          "medication_name": "Omeprazol",
          "dosage": "20 mg",
          "times_per_day": 1,
          "daily_times": [480],
          "duration_days": 14,
          "notes": "Nahorga, ovqatdan 30 daqiqa oldin"
        }
      },
      {
        "id": 504,
        "order": 4,
        "type": "analysis",
        "status": "current",
        "title": "Umumiy qon tahlili",
        "description": "Kamqonlik bor-yo'qligini tekshirish uchun.",
        "due_date": "2026-08-20",
        "payload": {
          "analysis_type": "blood_general",
          "preparation": "Nahorga topshiriladi, 8 soat ochlik"
        }
      },
      {
        "id": 506,
        "order": 6,
        "type": "consultation",
        "status": "locked",
        "title": "Gastroenterolog nazorati",
        "description": "Natijalar bilan qayta ko'rikka boring.",
        "due_date": "2026-09-05",
        "payload": {
          "specialty": "gastroenterolog",
          "reason": "Davolanish natijasini baholash"
        }
      }
    ]
  }
}
```

### `payload` qoidalari

`payload` — qadam turiga bog'liq. Mobil uni deep-link uchun ishlatadi:

- `medication` → `TreatmentEntity` yaratiladi (`daily_times` — kun boshidan
  daqiqalarda, `480` = 08:00; `TreatmentEntity.dailyTimes` bilan bir xil format)
- `analysis` → Analizlar bo'limi, `analysis_type` bilan
- `consultation` → Marketplace, `specialty` filtri bilan
- `lifestyle` → `{"diet_plan_id": 3}` yoki `null`
- `education` → `null` (`body` maydonidan o'qiladi)

---

## 3. `GET /navigator/roadmap/active/`

Home page uchun — **joriy aktiv roadmap**. Javob §2 bilan bir xil struktura,
faqat aktiv tashxis uchun. Aktiv tashxis yo'q bo'lsa:

**Javob 200:**

```json
{ "diagnosis": null }
```

Mobil bu holatda «Tashxis qo'shing» bo'sh holat ekranini ko'rsatadi.

---

## 4. `POST /navigator/diagnoses/from-image/`

**Tashxis qog'ozini rasmga olib yuklash → AI o'qiydi → roadmap quradi.**
Platformaga integratsiya qilinmagan shifokorlar uchun asosiy kirish nuqtasi.

**So'rov:** `multipart/form-data`

| Maydon | Tur | Izoh |
|--------|-----|------|
| `image` | file | JPEG/PNG, ≤10 MB |
| `note` | string? | Bemorning qo'shimcha izohi |

**Javob 201:** §2 dagi to'liq obyekt (`source` = `document`) + qo'shimcha:

```json
{
  "id": 42,
  "source": "document",
  "extraction": {
    "confidence": 0.86,
    "recognized_text": "Tashxis: Surunkali gastrit ...",
    "needs_review": false
  }
}
```

`confidence < 0.6` yoki `needs_review = true` bo'lsa — mobil bemordan
tasdiqlashni so'raydi («AI shuni o'qidi, to'g'rimi?»), roadmap darhol
qo'llanmaydi. Keys §9: AI mustaqil qaror qabul qilmaydi.

**Javob 422** — rasm o'qilmadi:

```json
{ "detail": "document_unreadable", "message": "Hujjatni o'qib bo'lmadi" }
```

---

## 5. `POST /navigator/diagnoses/`

Qo'lda tashxis kiritish.

**So'rov:**

```json
{ "title": "Surunkali gastrit", "icd10": null, "diagnosed_at": "2026-08-01" }
```

**Javob 201:** §2 dagi obyekt (`source` = `manual`).

---

## 6. `POST /navigator/steps/{id}/complete/`

Qadamni bajarilgan deb belgilash. Keyingi `locked` qadam `current` ga o'tadi.

**So'rov:** `{ "note": "Analiz topshirdim" }` (ixtiyoriy)

**Javob 200:**

```json
{
  "step": { "id": 504, "status": "done", "completed_at": "2026-08-15T09:12:00Z" },
  "roadmap_progress": { "total_steps": 8, "done_steps": 4, "percent": 50 },
  "unlocked_step_ids": [505]
}
```

---

## 7. `POST /navigator/triage/`

**Simptom → qaysi mutaxassisga borish kerak.** Keys talab #4.

**So'rov:**

```json
{
  "complaint": "Kecha kechqurundan beri ko'krak orqasida achishish kuchaydi",
  "diagnosis_id": 41
}
```

**Javob 200:**

```json
{
  "urgency": "routine",
  "summary": "Bu sizdagi GERD tashxisiga mos belgi. Xavfli emas, lekin dori tartibini shifokor bilan ko'rib chiqish kerak.",
  "advice": [
    "Bugun kechqurun ovqatdan keyin darhol yotmang",
    "Yostiqni 15 sm balandroq qo'ying"
  ],
  "recommended_specialties": [
    { "code": "gastroenterolog", "label": "Gastroenterolog", "reason": "Asosiy tashxisingiz bo'yicha" },
    { "code": "terapevt", "label": "Terapevt", "reason": "Umumiy holat baholash uchun" }
  ],
  "recommended_doctors": [
    {
      "id": 12,
      "full_name": "Aziza Karimova",
      "specialty": "Gastroenterolog",
      "photo_url": "https://...",
      "rating": 4.8,
      "experience_years": 11,
      "consultation_price": 150000,
      "is_online_available": true
    }
  ],
  "disclaimer": "Bu tashxis emas. Holatingiz yomonlashsa shifokorga murojaat qiling."
}
```

`urgency`: `emergency` (tez yordam) | `urgent` (24 soat ichida) | `routine` (rejali) | `self_care`.

---

## 8. `POST /navigator/chat/`

AI chatbot — bemor kontekstini (tashxis, roadmap, muolaja, analizlar, parhez,
salomatlik ko'rsatkichlari) **backend o'zi yig'adi**. Mobil faqat savol yuboradi.

**So'rov:**

```json
{
  "message": "Omeprazolni ovqatdan keyin ichsam bo'ladimi?",
  "conversation_id": "c-8831",
  "diagnosis_id": 41
}
```

**Javob 200:**

```json
{
  "conversation_id": "c-8831",
  "reply": "Omeprazol nahorga, ovqatdan 30 daqiqa oldin ichilganda yaxshiroq ta'sir qiladi...",
  "recommended_doctors": [],
  "related_step_ids": [502],
  "disclaimer": null
}
```

`recommended_doctors` bo'sh bo'lmasa — mobil javob ostida **gorizontal scroll**
shifokor kartalarini ko'rsatadi (§7 dagi bir xil struktura).

Streaming kerak bo'lsa: `POST /navigator/chat/stream/` — SSE, `data: {"delta": "..."}`.
Birinchi versiyada oddiy JSON yetarli.

---

## 9. `GET /navigator/context/` — *ixtiyoriy, debug uchun*

Backend AI'ga qanday kontekst uzatayotganini ko'rish. Prod'da yopiq bo'lishi mumkin.

---

## 10. Xatolik formati

Barcha 4xx/5xx javoblar:

```json
{ "detail": "machine_readable_code", "message": "Foydalanuvchiga ko'rsatiladigan matn" }
```

Mobil `detail` bo'yicha i18n kalitini tanlaydi, topilmasa `message` ni ko'rsatadi.

| `detail` | HTTP | Mobil xatti-harakati |
|----------|------|----------------------|
| `document_unreadable` | 422 | «Rasmni qaytadan oling» |
| `no_active_diagnosis` | 404 | Bo'sh holat ekrani |
| `ai_unavailable` | 503 | «AI hozir band, keyinroq urinib ko'ring» |
| `daily_limit_exceeded` | 429 | «Bugungi limit tugadi» |

---

## 11. Maxfiylik (keys §9)

- Tashxis qog'ozi rasmi **saqlanmaydi** — AI o'qib bo'lgach o'chiriladi,
  faqat ajratilgan matn qoladi.
- AI kontekstiga bemorning ismi/telefoni **uzatilmaydi** — faqat yosh, jins va
  tibbiy ma'lumot.
- Barcha javoblarda tizim o'zini shifokor o'rnida qo'ymaydi; `disclaimer` maydoni
  shu uchun.

---

## 12. Implementatsiya tartibi (backend uchun prioritet)

| # | Endpoint | Prioritet | Sabab |
|---|----------|-----------|-------|
| 1 | `GET /navigator/roadmap/active/` | 🔴 kritik | Home ekrani shusiz bo'sh |
| 2 | `POST /navigator/steps/{id}/complete/` | 🔴 kritik | Interaktivlik |
| 3 | `POST /navigator/chat/` | 🟠 yuqori | Keys talab #3 |
| 4 | `POST /navigator/diagnoses/from-image/` | 🟠 yuqori | Keys innovatsion qismi |
| 5 | `POST /navigator/triage/` | 🟡 o'rta | Keys talab #4 |
| 6 | Qolganlari | 🟢 past | Mock bilan ishlaydi |
