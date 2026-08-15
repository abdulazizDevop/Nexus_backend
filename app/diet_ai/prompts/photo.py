from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

PHOTO_ANALYSIS_UZ = """Rasmni diqqat bilan ko'zdan kechiring.

QADAM 1 — RASMDA OVQAT BORMI TEKSHIRING:
- Rasmda haqiqiy yeyish uchun taom/ichimlik/mahsulot bormi?
- Odam, hayvon, manzara, predmet, hujjat, skrinshot va shunga o'xshash "ovqat bo'lmagan" rasm bo'lsa — TAHLIL QILMANG.
- Ovqat va odam birga bo'lsa (masalan odam qo'lidagi olma) — OVQAT bor deb hisoblang.

AGAR OVQAT YO'Q BO'LSA:
- food_detected = false
- food_data = barcha raqamlar 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
- analysis_markdown = "Rasmda ovqat ko'rsatilmagan. Iltimos, ovqat rasmini yuklang."
- Boshqa hech nima yozmang, taxmin qilmang, tavsiya bermang.

AGAR OVQAT BOR BO'LSA:
- food_detected = true
- "analysis_markdown" (markdown, bemor ismi bilan murojaat):
  1. **Ovqat nomi** — rasmdagi taom (o'zbek oshxonasidan bo'lsa aniq nom)
  2. **Taxminiy kaloriya** — portsiya hajmiga qarab (~X kcal)
  3. **Makronutrientlar** — uglevod, oqsil, yog' taxminiy grammi
  4. **Asosiy masalliqlar** — nimalardan tayyorlangan
  5. **Parhez mosligi** — bemor cheklovlari va salomatligiga mos keladimi?
  6. **Tavsiyalar** — qanday yeyish, nima bilan birga, qachon
  Oxirida disclaimer: "Kaloriya va makronutrientlar taxminiy, aniq raqam uchun oziq-ovqat yorlig'ini tekshiring."
- "food_data" strukturali (⚠️ RAQAMLAR OBYEKTIV: estimated_calories va
  makronutrientlar FAQAT ovqat turi va porsiya hajmiga bog'liq — bemor profili,
  vazni, faoliyati yoki salomatligi bu RAQAMLARGA TA'SIR QILMAYDI. Bir xil
  ovqat va bir xil porsiya HAR DOIM bir xil raqam beradi. Profil faqat
  analysis_markdown matnidagi tavsiyaga ta'sir qiladi, raqamlarga emas):
  - food_name: ovqat nomi
  - estimated_calories: butun son (taxminiy jami kcal)
  - portion_grams: butun son (taxminiy gramm) yoki null
  - carbs_grams: butun son (uglevod, g) — majburiy
  - protein_grams: butun son (oqsil, g) — majburiy
  - fat_grams: butun son (yog', g) — majburiy
  - glycemic_load: "low" | "medium" | "high" (taomning glikemik yuki) yoki null
  - ingredients: 3-10 ta asosiy ingredient ro'yxati, har birida
    {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ RAQAM INTIZOMI (over-estimate va tebranishni kamaytirish — ANIQ SHU TARTIBDA hisoblang):
  ⚑ AVVAL — FOYDALANUVCHI BERGAN MIQDOR USTUN: agar pastdagi "Foydalanuvchi qo'shimcha" bo'limida
     gramm / porsiya / dona ko'rsatilgan bo'lsa, o'sha qiymatni ANIQ deb oling va butun hisobni
     o'shandan yuriting — vizual taxmin bilan ustidan yozmang. Masshtab bahosini (1-qadam) faqat
     bunday ma'lumot BERILMAGANDA qo'llang.
  1. MIQYOS (masshtab) ISHONCHINI baholang — porsiyani chamalashdan OLDIN. Rasmda hajmni
     o'lchaydigan real "tayanch" bormi: tovoq ⌀~25-27sm / kosa cheti · qoshiq/vilka ~19sm/pichoq ·
     qo'l kafti ~10sm yoki bosh barmoq eni ~2sm · stol yuzasi · stakan/piyola ~250ml · tanga ·
     qadoq/etiketka? Tayanch BOR bo'lsa — ishonch YUQORI, hajmni o'sha tayanchga NISBATAN o'lchang.
     Yaqindan olingan, kadrni to'ldirgan yoki tayanch ko'rinmaydigan (close-up) rasmda — ishonch PAST.
  2. ⚠️ ZUM ≠ HAJM: kamera yaqin turgani yoki ovqat kadrni to'ldirgani porsiya KATTA degani EMAS —
     close-up rasmda taom bor holidan kattaroq ko'rinadi. Bu eng ko'p uchraydigan over-estimate xatosi.
     Close-up'ni katta porsiya deb o'qimang; ikkilanganda porsiyani KATTALASHTIRMANG, kam tomonga baholang.
  3. Ishonch PAST bo'lsa — o'zingizcha katta porsiya taxmin qilmang, quyidagi ODATIY (bitta kishilik)
     porsiyani oling va oraliqning past-o'rta qiymatini tanlang, HECH QACHON maksimumini emas:
     lavash/o'rama (döner) ~250-350g · bir tovoq osh/palov ~250-400g · kosa sho'rva/lag'mon ~300-450g ·
     bitta somsa ~100-160g · bitta manti ~50-70g (donasiga) · non/lepyoshka bo'lagi ~60-90g
     (butun non ~250-400g) · salat/garnir ~150-250g · sendvich/burger ~150-300g ·
     bitta kabob sixi ~90-120g · shirinlik bo'lagi ~80-150g · stakan ichimlik ~250ml · piyola choy ~200ml.
  4. Bitta ovqat aniq ko'rinsa, portion_grams shu oraliqlarning yuqori chegarasidan OSHMASIN. Undan
     oshirish faqat bir nechta porsiya ANIQ ko'ringanda mumkin (bir necha tovoq · umumiy laganda
     cho'mich bilan · bir necha kishilik ulush).
  5. Har ingredient grammini alohida bering; grammlar yig'indisi porsiya grammiga teng bo'lsin.
  6. Har ingredient kaloriyasi = gramm × (100g_zichligi ÷ 100). 100g uchun taxminiy zichliklar:
     guruch/makaron(pishirilgan) 130 · non/lepyoshka 270 · go'sht(qovurilgan) 250 · tovuq 165 ·
     baliq 130 · tuxum 155 · falafel 330 · kartoshka(qovurilgan) 210 · dukkakli(no'xat/loviya) 130 ·
     sabzavot(piyoz/sabzi/pomidor/bodring/salat) 30 · pishloq 300 · smetana/sous 200 ·
     o'simlik yog'i/sariyog' 850 (AMMO bir porsiyada yog' odatda 5-25g — ko'p yozmang).
     Ro'yxatda yo'q mahsulot uchun shu darajadagi real zichlikni oling.
  7. estimated_calories, carbs_grams, protein_grams, fat_grams = ingredientlar yig'indisiga
     AYNAN teng bo'lsin (farq 2%dan oshmasin).
  8. analysis_markdown dagi barcha raqamlar food_data BILAN BIR XIL bo'lsin — avval food_data ni
     hisoblang, keyin markdown matnini o'sha raqamlar bilan yozing.
"""

PHOTO_ANALYSIS_RU = """Внимательно рассмотрите изображение.

ШАГ 1 — ПРОВЕРЬТЕ ЕСТЬ ЛИ ЕДА НА ИЗОБРАЖЕНИИ:
- На изображении действительно есть еда/напиток/продукт для употребления?
- Если это человек, животное, пейзаж, предмет, документ, скриншот и т.п. — НЕ АНАЛИЗИРУЙТЕ.
- Если еда и человек вместе (например яблоко в руке) — ЕДА ЕСТЬ.

ЕСЛИ ЕДЫ НЕТ:
- food_detected = false
- food_data = все числа 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
- analysis_markdown = "На изображении не показана еда. Пожалуйста, загрузите фото еды."
- Больше ничего не пишите, не предполагайте, не рекомендуйте.

ЕСЛИ ЕДА ЕСТЬ:
- food_detected = true
- "analysis_markdown" (markdown, обращение по имени):
  1. **Название блюда** — что изображено (узбекская кухня — точное название)
  2. **Примерная калорийность** — по размеру порции (~X ккал)
  3. **Макронутриенты** — углеводы, белки, жиры в граммах
  4. **Основные ингредиенты** — из чего приготовлено
  5. **Соответствие диете** — подходит ли с учётом ограничений?
  6. **Рекомендации** — как есть, с чем сочетать, когда
  В конце дисклеймер: "Калории и макронутриенты приблизительные, для точных значений проверьте этикетку продукта."
- "food_data" структурированные (⚠️ ЦИФРЫ ОБЪЕКТИВНЫ: estimated_calories и
  макронутриенты зависят ТОЛЬКО от типа блюда и размера порции — профиль
  пациента, вес, активность и здоровье НЕ ВЛИЯЮТ на эти цифры. Одно и то же
  блюдо и порция ВСЕГДА дают одинаковые цифры. Профиль влияет только на текст
  рекомендаций в analysis_markdown, не на цифры):
  - food_name: название блюда
  - estimated_calories: целое число (примерные общие ккал)
  - portion_grams: целое число (примерные граммы) или null
  - carbs_grams: целое число (углеводы, г) — обязательно
  - protein_grams: целое число (белки, г) — обязательно
  - fat_grams: целое число (жиры, г) — обязательно
  - glycemic_load: "low" | "medium" | "high" (гликемическая нагрузка) или null
  - ingredients: список из 3-10 основных ингредиентов, у каждого
    {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ ТОЧНОСТЬ ЧИСЕЛ (чтобы снизить завышение и разброс — считай СТРОГО в этом порядке):
  ⚑ СНАЧАЛА — ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ГЛАВНЕЕ: если ниже в разделе "Foydalanuvchi qo'shimcha" указаны
     граммы / порция / штуки, считай их ТОЧНЫМИ и веди весь расчёт от них — не переписывай визуальной
     оценкой. Оценку масштаба (шаг 1) применяй ТОЛЬКО если таких данных нет.
  1. Оцени УВЕРЕННОСТЬ В МАСШТАБЕ — ДО оценки порции. Есть ли на фото реальная "опора" для
     измерения объёма: тарелка ⌀~25-27см / край миски · ложка/вилка ~19см/нож · ладонь ~10см
     или ширина большого пальца ~2см · поверхность стола · стакан/пиала ~250мл · монета ·
     упаковка/этикетка? Если опора ЕСТЬ — уверенность ВЫСОКАЯ, измеряй объём ОТНОСИТЕЛЬНО неё.
     Снятое вблизи, заполняющее кадр или без видимой опоры (close-up) фото — уверенность НИЗКАЯ.
  2. ⚠️ ЗУМ ≠ ОБЪЁМ: близость камеры или то, что еда заполняет кадр, НЕ означает большую порцию —
     на близком фото еда выглядит крупнее, чем есть. Это самая частая ошибка завышения.
     Не читай close-up как большую порцию; при сомнении НЕ увеличивай порцию, оценивай в меньшую сторону.
  3. Если уверенность НИЗКАЯ — не выдумывай большую порцию, бери ОБЫЧНУЮ (на одного человека) и выбирай
     нижне-среднее значение диапазона, НИКОГДА не максимум:
     лаваш/ролл (донер) ~250-350г · тарелка плова ~250-400г · миска супа/лагмана ~300-450г ·
     одна самса ~100-160г · один манты ~50-70г (за штуку) · кусок лепёшки ~60-90г
     (целая лепёшка ~250-400г) · салат/гарнир ~150-250г · сэндвич/бургер ~150-300г ·
     один шампур кебаба ~90-120г · кусок десерта ~80-150г · стакан напитка ~250мл · пиала чая ~200мл.
  4. Если явно видна одна порция, portion_grams НЕ должен превышать верхнюю границу диапазона. Превысить
     можно только когда ЯВНО видно несколько порций (несколько тарелок · общее блюдо с половником ·
     доля на несколько человек).
  5. Укажи граммы каждого ингредиента; их сумма = граммам порции.
  6. Калории ингредиента = граммы × (плотность_на_100г ÷ 100). Плотности на 100г (примерно):
     рис/макароны(варёные) 130 · хлеб/лепёшка 270 · мясо(жареное) 250 · курица 165 · рыба 130 ·
     яйцо 155 · фалафель 330 · картофель(жареный) 210 · бобовые(нут/фасоль) 130 ·
     овощи(лук/морковь/помидор/огурец/салат) 30 · сыр 300 · сметана/соус 200 ·
     раст. масло/сливочное 850 (НО масла в порции обычно 5-25г — не завышай).
     Для продукта не из списка возьми реалистичную плотность того же уровня.
  7. estimated_calories, carbs_grams, protein_grams, fat_grams = сумме ингредиентов ТОЧНО (расхождение ≤2%).
  8. Все числа в analysis_markdown ДОЛЖНЫ совпадать с food_data — сначала посчитай food_data, потом пиши текст.
"""

PHOTO_ANALYSIS_UZ_CYRL = """Расмни диққат билан кўздан кечиринг.

ҚАДАМ 1 — РАСМДА ОВҚАТ БОРМИ ТЕКШИРИНГ:
- Расмда ҳақиқий ейиш учун таом/ичимлик/маҳсулот борми?
- Одам, ҳайвон, манзара, предмет, ҳужжат, скриншот ва шунга ўхшаш "овқат бўлмаган" расм бўлса — ТАҲЛИЛ ҚИЛМАНГ.
- Овқат ва одам бирга бўлса (масалан одам қўлидаги олма) — ОВҚАТ бор деб ҳисобланг.

АГАР ОВҚАТ ЙЎҚ БЎЛСА:
- food_detected = false
- food_data = барча рақамлар 0 (estimated_calories=0, carbs_grams=0, protein_grams=0, fat_grams=0), food_name = ""
- analysis_markdown = "Расмда овқат кўрсатилмаган. Илтимос, овқат расмини юкланг."
- Бошқа ҳеч нима ёзманг, тахмин қилманг, тавсия берманг.

АГАР ОВҚАТ БОР БЎЛСА:
- food_detected = true
- "analysis_markdown" (markdown, бемор исми билан мурожаат):
  1. **Овқат номи** — расмдаги таом (ўзбек ошхонасидан бўлса аниқ ном)
  2. **Тахминий калория** — порция ҳажмига қараб (~X kcal)
  3. **Макронутриентлар** — углевод, оқсил, ёғ тахминий грамми
  4. **Асосий масаллиқлар** — нималардан тайёрланган
  5. **Парҳез мослиги** — бемор чекловлари ва саломатлигига мос келадими?
  6. **Тавсиялар** — қандай ейиш, нима билан бирга, қачон
  Охирида disclaimer: "Калория ва макронутриентлар тахминий, аниқ рақам учун озиқ-овқат ёрлиғини текширинг."
- "food_data" структурали (⚠️ РАҚАМЛАР ОБЪЕКТИВ: estimated_calories ва
  макронутриентлар ФАҚАТ овқат тури ва порция ҳажмига боғлиқ — бемор профили,
  вазни, фаолияти ёки саломатлиги бу РАҚАМЛАРГА ТАЪСИР ҚИЛМАЙДИ. Бир хил
  овқат ва бир хил порция ҲАР ДОИМ бир хил рақам беради. Профил фақат
  analysis_markdown матнидаги тавсияга таъсир қилади, рақамларга эмас):
  - food_name: овқат номи
  - estimated_calories: бутун сон (тахминий жами kcal)
  - portion_grams: бутун сон (тахминий грамм) ёки null
  - carbs_grams: бутун сон (углевод, г) — мажбурий
  - protein_grams: бутун сон (оқсил, г) — мажбурий
  - fat_grams: бутун сон (ёғ, г) — мажбурий
  - glycemic_load: "low" | "medium" | "high" (гликемик юк) ёки null
  - ingredients: 3-10 та асосий ингредиент рўйхати, ҳар бирида
    {name, grams, calories, carbs_g, protein_g, fat_g}.

⚠️ РАҚАМ ИНТИЗОМИ (over-estimate ва тебранишни камайтириш — АНИҚ ШУ ТАРТИБДА ҳисобланг):
  ⚑ АВВАЛ — ФОЙДАЛАНУВЧИ БЕРГАН МИҚДОР УСТУН: агар пастдаги "Foydalanuvchi qo'shimcha" бўлимида
     грамм / порсия / дона кўрсатилган бўлса, ўша қийматни АНИҚ деб олинг ва бутун ҳисобни ўшандан
     юритинг — визуал тахмин билан устидан ёзманг. Масштаб баҳосини (1-қадам) фақат бундай маълумот
     БЕРИЛМАГАНДА қўлланг.
  1. МИҚЁС (масштаб) ИШОНЧИНИ баҳоланг — порсияни чамалашдан ОЛДИН. Расмда ҳажмни ўлчайдиган реал
     "таянч" борми: товоқ ⌀~25-27см / коса чети · қошиқ/вилка ~19см/пичоқ · қўл кафти ~10см ёки
     бош бармоқ эни ~2см · стол юзаси · стакан/пиёла ~250мл · танга · қадоқ/этикетка? Таянч БОР бўлса —
     ишонч ЮҚОРИ, ҳажмни ўша таянчга НИСБАТАН ўлчанг. Яқиндан олинган, кадрни тўлдирган ёки таянч
     кўринмайдиган (close-up) расмда — ишонч ПАСТ.
  2. ⚠️ ЗУМ ≠ ҲАЖМ: камера яқин тургани ёки овқат кадрни тўлдиргани порсия КАТТА дегани ЭМАС —
     close-up расмда таом бор ҳолидан каттароқ кўринади. Бу энг кўп учрайдиган over-estimate хатоси.
     Close-up'ни катта порсия деб ўқиманг; иккиланганда порсияни КАТТАЛАШТИРМАНГ, кам томонга баҳоланг.
  3. Ишонч ПАСТ бўлса — ўзингизча катта порсия тахмин қилманг, қуйидаги ОДАТИЙ (битта кишилик)
     порсияни олинг ва оралиқнинг паст-ўрта қийматини танланг, ҲЕЧ ҚАЧОН максимумини эмас:
     лаваш/ўрама (донер) ~250-350г · бир товоқ ош/палов ~250-400г · коса шўрва/лағмон ~300-450г ·
     битта самса ~100-160г · битта манти ~50-70г (донасига) · нон/лепёшка бўлаги ~60-90г
     (бутун нон ~250-400г) · салат/гарнир ~150-250г · сэндвич/бургер ~150-300г ·
     битта кабоб сихи ~90-120г · ширинлик бўлаги ~80-150г · стакан ичимлик ~250мл · пиёла чой ~200мл.
  4. Битта овқат аниқ кўринса, portion_grams шу оралиқларнинг юқори чегарасидан ОШМАСИН. Ундан
     ошириш фақат бир нечта порсия АНИҚ кўрингандагина мумкин (бир неча товоқ · умумий лаганда
     чўмич билан · бир неча кишилик улуш).
  5. Ҳар ингредиент граммини алоҳида беринг; граммлар йиғиндиси порсия граммига тенг бўлсин.
  6. Ҳар ингредиент калорияси = грамм × (100г_зичлиги ÷ 100). 100г учун тахминий зичликлар:
     гуруч/макарон(пиширилган) 130 · нон/лепёшка 270 · гўшт(қовурилган) 250 · товуқ 165 · балиқ 130 ·
     тухум 155 · фалафель 330 · картошка(қовурилган) 210 · дуккакли(нўхат/ловия) 130 ·
     сабзавот(пиёз/сабзи/помидор/бодринг/салат) 30 · пишлоқ 300 · сметана/соус 200 ·
     ўсимлик ёғи/сариёғ 850 (АММО бир порсияда ёғ одатда 5-25г — кўп ёзманг).
     Рўйхатда йўқ маҳсулот учун шу даражадаги реал зичликни олинг.
  7. estimated_calories, carbs_grams, protein_grams, fat_grams = ингредиентлар йиғиндисига АЙНАН тенг (фарқ 2%дан ошмасин).
  8. analysis_markdown даги барча рақамлар food_data БИЛАН БИР ХИЛ бўлсин — аввал food_data ни ҳисобланг, кейин матн.
"""


# Ovqat MATN tahlili uchun prompt (rasmsiz — foydalanuvchi nomi + miqdorni yozadi).
# Porsiya oraliqlari + zichlik jadvali PHOTO_ANALYSIS bilan AYNAN bir xil (kalibrlashda
# ikkalasi birga yangilanadi). Rasm/masshtab/zoom mantiqi yo'q — matnда kerak emas.

def get_photo_analysis_prompt(language: str) -> str:
    if language == "ru":
        return PHOTO_ANALYSIS_RU
    if language in ("cyr", "uz-cyrl"):
        return PHOTO_ANALYSIS_UZ_CYRL
    return PHOTO_ANALYSIS_UZ
