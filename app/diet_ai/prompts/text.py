from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

TEXT_ANALYSIS_UZ = """Foydalanuvchi YOZGAN ovqat ma'lumotini tahlil qiling (rasm YO'Q — faqat matn).

QADAM 1 — HAQIQIY OVQATMI TEKSHIRING:
- Berilgan nom haqiqiy yeyiladigan taom/ichimlik/mahsulotmi?
- Bema'ni yoki ovqatga aloqasiz matn (masalan "asdf", tasodifiy harflar, hazil) bo'lsa — TAHLIL QILMANG:
  - food_detected = false
  - food_data = barcha raqamlar 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
  - analysis_markdown = "Bu taomni aniqlay olmadim. Iltimos, ovqat nomini aniqroq yozing (masalan: 'bir tovoq osh')."
  - Boshqa hech nima yozmang.

AGAR HAQIQIY OVQAT BO'LSA:
- food_detected = true
- "analysis_markdown" (markdown, bemor ismi bilan murojaat):
  1. **Ovqat nomi** — foydalanuvchi yozgan taom (o'zbek oshxonasidan bo'lsa aniq nom)
  2. **Taxminiy kaloriya** — porsiya hajmiga qarab (~X kcal)
  3. **Makronutrientlar** — uglevod, oqsil, yog' taxminiy grammi
  4. **Asosiy masalliqlar** — nimalardan tayyorlangan
  5. **Parhez mosligi** — bemor cheklovlari va salomatligiga mos keladimi?
  6. **Tavsiyalar** — qanday yeyish, nima bilan birga, qachon
  Oxirida disclaimer: "Kaloriya va makronutrientlar taxminiy, aniq raqam uchun oziq-ovqat yorlig'ini tekshiring."
- "food_data" strukturali (⚠️ RAQAMLAR OBYEKTIV: estimated_calories va makronutrientlar FAQAT
  ovqat turi va porsiya hajmiga bog'liq — bemor profili, vazni, faoliyati yoki salomatligi bu
  RAQAMLARGA TA'SIR QILMAYDI. Profil faqat analysis_markdown tavsiyasiga ta'sir qiladi):
  - food_name, estimated_calories, portion_grams (yoki null), carbs_grams, protein_grams,
    fat_grams (majburiy), glycemic_load ("low"|"medium"|"high" yoki null),
    ingredients: 3-10 ta, har birida {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ RAQAM INTIZOMI (over-estimate va tebranishni kamaytirish — ANIQ SHU TARTIBDA hisoblang):
  1. PORSIYA MANBASI: agar foydalanuvchi gramm / porsiya / dona bergan bo'lsa — o'sha ANIQ deb ol va
     butun hisobni o'shandan yurit. Faqat BERILMAGANDA quyidagi ODATIY (bitta kishilik) porsiyani ol,
     oraliqning past-o'rta qiymatini, HECH QACHON maksimumini emas:
     lavash/o'rama (döner) ~250-350g · bir tovoq osh/palov ~250-400g · kosa sho'rva/lag'mon ~300-450g ·
     bitta somsa ~100-160g · bitta manti ~50-70g (donasiga) · non/lepyoshka bo'lagi ~60-90g
     (butun non ~250-400g) · salat/garnir ~150-250g · sendvich/burger ~150-300g ·
     bitta kabob sixi ~90-120g · shirinlik bo'lagi ~80-150g · stakan ichimlik ~250ml · piyola choy ~200ml.
  2. Har ingredient grammini alohida ber; grammlar yig'indisi porsiya grammiga teng bo'lsin.
  3. Har ingredient kaloriyasi = gramm × (100g_zichligi ÷ 100). 100g uchun taxminiy zichliklar:
     guruch/makaron(pishirilgan) 130 · non/lepyoshka 270 · go'sht(qovurilgan) 250 · tovuq 165 ·
     baliq 130 · tuxum 155 · falafel 330 · kartoshka(qovurilgan) 210 · dukkakli(no'xat/loviya) 130 ·
     sabzavot(piyoz/sabzi/pomidor/bodring/salat) 30 · pishloq 300 · smetana/sous 200 ·
     o'simlik yog'i/sariyog' 850 (AMMO bir porsiyada yog' odatda 5-25g — ko'p yozmang).
     Ro'yxatda yo'q mahsulot uchun shu darajadagi real zichlikni oling.
  4. estimated_calories, carbs_grams, protein_grams, fat_grams = ingredientlar yig'indisiga AYNAN teng (farq 2%dan oshmasin).
  5. analysis_markdown dagi barcha raqamlar food_data BILAN BIR XIL bo'lsin — avval food_data, keyin matn.
"""

TEXT_ANALYSIS_RU = """Проанализируйте блюдо, которое пользователь ОПИСАЛ ТЕКСТОМ (изображения НЕТ — только текст).

ШАГ 1 — ПРОВЕРЬТЕ ЭТО РЕАЛЬНАЯ ЕДА:
- Указанное название — реальная еда/напиток/продукт для употребления?
- Если это бессмысленный или не связанный с едой текст (например "asdf", случайные буквы, шутка) — НЕ АНАЛИЗИРУЙТЕ:
  - food_detected = false
  - food_data = все числа 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
  - analysis_markdown = "Не удалось распознать это блюдо. Пожалуйста, укажите название точнее (например: 'тарелка плова')."
  - Больше ничего не пишите.

ЕСЛИ ЭТО РЕАЛЬНАЯ ЕДА:
- food_detected = true
- "analysis_markdown" (markdown, обращение по имени):
  1. **Название блюда** — то, что описал пользователь (узбекская кухня — точное название)
  2. **Примерная калорийность** — по размеру порции (~X ккал)
  3. **Макронутриенты** — углеводы, белки, жиры в граммах
  4. **Основные ингредиенты** — из чего приготовлено
  5. **Соответствие диете** — подходит ли с учётом ограничений?
  6. **Рекомендации** — как есть, с чем сочетать, когда
  В конце дисклеймер: "Калории и макронутриенты приблизительные, для точных значений проверьте этикетку продукта."
- "food_data" структурированные (⚠️ ЦИФРЫ ОБЪЕКТИВНЫ: estimated_calories и макронутриенты зависят
  ТОЛЬКО от типа блюда и размера порции — профиль пациента, вес, активность и здоровье НЕ ВЛИЯЮТ на
  эти цифры. Профиль влияет только на текст рекомендаций в analysis_markdown):
  - food_name, estimated_calories, portion_grams (или null), carbs_grams, protein_grams,
    fat_grams (обязательно), glycemic_load ("low"|"medium"|"high" или null),
    ingredients: 3-10 шт, у каждого {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ ТОЧНОСТЬ ЧИСЕЛ (чтобы снизить завышение и разброс — считай СТРОГО в этом порядке):
  1. ИСТОЧНИК ПОРЦИИ: если пользователь указал граммы / порцию / штуки — считай это ТОЧНЫМ и веди
     весь расчёт от него. Только ЕСЛИ НЕ указано — бери ОБЫЧНУЮ (на одного человека) порцию ниже,
     нижне-среднее значение диапазона, НИКОГДА не максимум:
     лаваш/ролл (донер) ~250-350г · тарелка плова ~250-400г · миска супа/лагмана ~300-450г ·
     одна самса ~100-160г · один манты ~50-70г (за штуку) · кусок лепёшки ~60-90г
     (целая лепёшка ~250-400г) · салат/гарнир ~150-250г · сэндвич/бургер ~150-300г ·
     один шампур кебаба ~90-120г · кусок десерта ~80-150г · стакан напитка ~250мл · пиала чая ~200мл.
  2. Укажи граммы каждого ингредиента; их сумма = граммам порции.
  3. Калории ингредиента = граммы × (плотность_на_100г ÷ 100). Плотности на 100г (примерно):
     рис/макароны(варёные) 130 · хлеб/лепёшка 270 · мясо(жареное) 250 · курица 165 · рыба 130 ·
     яйцо 155 · фалафель 330 · картофель(жареный) 210 · бобовые(нут/фасоль) 130 ·
     овощи(лук/морковь/помидор/огурец/салат) 30 · сыр 300 · сметана/соус 200 ·
     раст. масло/сливочное 850 (НО масла в порции обычно 5-25г — не завышай).
     Для продукта не из списка возьми реалистичную плотность того же уровня.
  4. estimated_calories, carbs_grams, protein_grams, fat_grams = сумме ингредиентов ТОЧНО (расхождение ≤2%).
  5. Все числа в analysis_markdown ДОЛЖНЫ совпадать с food_data — сначала посчитай food_data, потом текст.
"""

TEXT_ANALYSIS_UZ_CYRL = """Фойдаланувчи ЁЗГАН овқат маълумотини таҳлил қилинг (расм ЙЎҚ — фақат матн).

ҚАДАМ 1 — ҲАҚИҚИЙ ОВҚАТМИ ТЕКШИРИНГ:
- Берилган ном ҳақиқий ейиладиган таом/ичимлик/маҳсулотми?
- Бемаъни ёки овқатга алоқасиз матн (масалан "asdf", тасодифий ҳарфлар, ҳазил) бўлса — ТАҲЛИЛ ҚИЛМАНГ:
  - food_detected = false
  - food_data = барча рақамлар 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
  - analysis_markdown = "Бу таомни аниқлай олмадим. Илтимос, овқат номини аниқроқ ёзинг (масалан: 'бир товоқ ош')."
  - Бошқа ҳеч нима ёзманг.

АГАР ҲАҚИҚИЙ ОВҚАТ БЎЛСА:
- food_detected = true
- "analysis_markdown" (markdown, бемор исми билан мурожаат):
  1. **Овқат номи** — фойдаланувчи ёзган таом (ўзбек ошхонасидан бўлса аниқ ном)
  2. **Тахминий калория** — порция ҳажмига қараб (~X kcal)
  3. **Макронутриентлар** — углевод, оқсил, ёғ тахминий грамми
  4. **Асосий масаллиқлар** — нималардан тайёрланган
  5. **Парҳез мослиги** — бемор чекловлари ва саломатлигига мос келадими?
  6. **Тавсиялар** — қандай ейиш, нима билан бирга, қачон
  Охирида disclaimer: "Калория ва макронутриентлар тахминий, аниқ рақам учун озиқ-овқат ёрлиғини текширинг."
- "food_data" структурали (⚠️ РАҚАМЛАР ОБЪЕКТИВ: estimated_calories ва макронутриентлар ФАҚАТ
  овқат тури ва порция ҳажмига боғлиқ — бемор профили, вазни, фаолияти ёки саломатлиги бу
  РАҚАМЛАРГА ТАЪСИР ҚИЛМАЙДИ. Профил фақат analysis_markdown тавсиясига таъсир қилади):
  - food_name, estimated_calories, portion_grams (ёки null), carbs_grams, protein_grams,
    fat_grams (мажбурий), glycemic_load ("low"|"medium"|"high" ёки null),
    ingredients: 3-10 та, ҳар бирида {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ РАҚАМ ИНТИЗОМИ (over-estimate ва тебранишни камайтириш — АНИҚ ШУ ТАРТИБДА ҳисобланг):
  1. ПОРЦИЯ МАНБАСИ: агар фойдаланувчи грамм / порция / дона берган бўлса — ўша АНИҚ деб ол ва бутун
     ҳисобни ўшандан юрит. Фақат БЕРИЛМАГАНДА қуйидаги ОДАТИЙ (битта кишилик) порцияни ол,
     оралиқнинг паст-ўрта қийматини, ҲЕЧ ҚАЧОН максимумини эмас:
     лаваш/ўрама (донер) ~250-350г · бир товоқ ош/палов ~250-400г · коса шўрва/лағмон ~300-450г ·
     битта самса ~100-160г · битта манти ~50-70г (донасига) · нон/лепёшка бўлаги ~60-90г
     (бутун нон ~250-400г) · салат/гарнир ~150-250г · сэндвич/бургер ~150-300г ·
     битта кабоб сихи ~90-120г · ширинлик бўлаги ~80-150г · стакан ичимлик ~250мл · пиёла чой ~200мл.
  2. Ҳар ингредиент граммини алоҳида бер; граммлар йиғиндиси порция граммига тенг бўлсин.
  3. Ҳар ингредиент калорияси = грамм × (100г_зичлиги ÷ 100). 100г учун тахминий зичликлар:
     гуруч/макарон(пиширилган) 130 · нон/лепёшка 270 · гўшт(қовурилган) 250 · товуқ 165 · балиқ 130 ·
     тухум 155 · фалафель 330 · картошка(қовурилган) 210 · дуккакли(нўхат/ловия) 130 ·
     сабзавот(пиёз/сабзи/помидор/бодринг/салат) 30 · пишлоқ 300 · сметана/соус 200 ·
     ўсимлик ёғи/сариёғ 850 (АММО бир порсияда ёғ одатда 5-25г — кўп ёзманг).
     Рўйхатда йўқ маҳсулот учун шу даражадаги реал зичликни олинг.
  4. estimated_calories, carbs_grams, protein_grams, fat_grams = ингредиентлар йиғиндисига АЙНАН тенг (фарқ 2%дан ошмасин).
  5. analysis_markdown даги барча рақамлар food_data БИЛАН БИР ХИЛ бўлсин — аввал food_data, кейин матн.
"""


# Gemini response_schema — kafolatlangan JSON struktura

def get_text_analysis_prompt(language: str) -> str:
    if language == "ru":
        return TEXT_ANALYSIS_RU
    if language in ("cyr", "uz-cyrl"):
        return TEXT_ANALYSIS_UZ_CYRL
    return TEXT_ANALYSIS_UZ
