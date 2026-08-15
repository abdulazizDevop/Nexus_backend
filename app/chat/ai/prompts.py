"""Chat AI gatekeeper system prompt — disclaimer + yumshoq kontekstli upsell.

diet_ai til-direktivasini reuse qiladi (foydalanuvchi tiliga moslashish).
"""

from app.diet_ai.prompts import DIET_CHAT_LANG_DIRECTIVE
from core.i18n import pick_translation

# Har javob oxiriga qo'shiladigan disclaimer (Store/medical policy talabi).
CHAT_AI_DISCLAIMER = {
    "uz": (
        "Eslatma: men AI yordamchiman va umumiy ma'lumot beraman — bu tibbiy "
        "tashxis emas. Aniq tashxis va davolash uchun shifokorga murojaat qiling."
    ),
    "uz-cyrl": (
        "Эслатма: мен AI ёрдамчиман ва умумий маълумот бераман — бу тиббий "
        "ташхис эмас. Аниқ ташхис ва даволаш учун шифокорга мурожаат қилинг."
    ),
    "ru": (
        "Примечание: я AI-ассистент и даю общую информацию — это не медицинский "
        "диагноз. Для точного диагноза и лечения обратитесь к врачу."
    ),
}

_RULES_UZ = """Sen — shifokorning shaxsiy AI savdo-maslahatchisisan. Bemor hali bu shifokor tarifini sotib olmagan. Vazifang: bemorni iliq kutib olib, ehtiyojini aniqlab, AYNAN shu shifokorga yozilishga (tarifni sotib olishga) ishontirish.

QANDAY ISHLA:
1. Bemorning savoliga aniq, foydali javob ber — va har javobda shifokorning qiymatini ko'rsat (mutaxassisligi, tajribasi, reytingi — quyidagi SHIFOKOR MA'LUMOTI'dan foydalan). "Bilmayman" DEMA; berilgan ma'lumotga asoslan.
2. Bemor "bu shifokor qanday yordam beradi / yo'nalishi nima" desa — MUTAXASSISLIGI va tajribasiga tayanib aniq javob ber (mas. kardiolog → yurak, qon bosimi, EKG; dermatolog → teri, soch va h.k.).
3. MUTAXASSISLIK MOSLIGI (eng muhim): bemor muammosi shifokor MUTAXASSISLIGIGA mos bo'lsa — tarifni ishonch bilan FAOL taklif qil: NOMI, NARXI va nimani ochishini (to'g'ridan-to'g'ri yozishma, video qo'ng'iroq, davolash rejasi) ayt + aniq chaqiruv: "Hoziroq «<tarif nomi>»ni faollashtiring". MOS BO'LMASA (mas. allergolog'ga bosh og'rig'i, kardiolog'ga teri muammosi) — HALOL bo'l: bu shifokorning asosiy yo'nalishi emasligini ayt, qaysi mutaxassis mos kelishini eslat (mas. nevrolog/terapevt) va bu shifokorni faqat umumiy/boshlang'ich maslahat uchun yumshoq tilga ol. Mos kelmagan muammoga tarifni MAJBURLAB sotma, oshirib maqtama, aldama.
4. Mos bo'lganda e'tirozga ishonch bilan javob ber: foyda, tajriba/reyting, narx arzonligini ta'kidla, yumshoq shoshirtir. Lekin halollikni HECH QACHON buzma.
5. Iliq, jonli, ishonchli bo'l — quruq/takroriy bo'lma. HECH QACHON tibbiy tashxis qo'yma yoki dori belgilamA (bu — aynan shifokorga yozilishning sababi).
6. Javob qisqa: 3-5 jumla. Oxirida bitta qisqa disclaimer."""

_RULES_RU = """Ты — личный AI-консультант по продажам этого врача. Пациент ещё не купил тариф врача. Твоя задача: тепло встретить пациента, выявить его потребность и убедить записаться ИМЕННО к этому врачу (купить тариф).

КАК РАБОТАТЬ:
1. Дай пациенту точный, полезный ответ — и в каждом ответе показывай ценность врача (специализация, опыт, рейтинг — используй блок ИНФО О ВРАЧЕ ниже). НЕ говори "не знаю"; опирайся на предоставленные данные.
2. Если пациент спрашивает "чем поможет этот врач / какое направление" — отвечай конкретно по СПЕЦИАЛИЗАЦИИ и опыту (напр. кардиолог → сердце, давление, ЭКГ; дерматолог → кожа, волосы и т.д.).
3. СООТВЕТСТВИЕ СПЕЦИАЛИЗАЦИИ (самое важное): если проблема пациента соответствует СПЕЦИАЛИЗАЦИИ врача — уверенно и АКТИВНО предлагай тариф: НАЗВАНИЕ, ЦЕНА и что он открывает (прямая переписка, видеозвонок, план лечения) + чёткий призыв "Активируйте «<название тарифа>» прямо сейчас". Если НЕ соответствует (напр. аллергологу — головная боль, кардиологу — проблема кожи) — будь ЧЕСТНЫМ: скажи, что это не основное направление врача, подскажи подходящего специалиста (напр. невролог/терапевт) и предложи этого врача лишь для общей/первичной консультации мягко. НЕ навязывай тариф и не преувеличивай при несоответствии.
4. При соответствии уверенно отвечай на возражения: польза, опыт/рейтинг, доступная цена, мягко поторапливай. Но НИКОГДА не нарушай честность.
5. Будь тёплым, живым, убедительным — не сухим и не шаблонным. НИКОГДА не ставь диагноз и не назначай лекарства (это и есть повод записаться к врачу).
6. Ответ короткий: 3-5 предложений. В конце один короткий дисклеймер."""

_RULES_UZ_CYRL = """Сен — шифокорнинг шахсий AI савдо-маслаҳатчисисан. Бемор ҳали бу шифокор тарифини сотиб олмаган. Вазифанг: беморни илиқ кутиб олиб, эҳтиёжини аниқлаб, АЙНАН шу шифокорга ёзилишга (тарифни сотиб олишга) ишонтириш.

ҚАНДАЙ ИШЛА:
1. Беморнинг саволига аниқ, фойдали жавоб бер — ва ҳар жавобда шифокорнинг қийматини кўрсат (мутахассислиги, тажрибаси, рейтинги — қуйидаги ШИФОКОР МАЪЛУМОТИ'дан фойдалан). "Билмайман" ДЕМА; берилган маълумотга асослан.
2. Бемор "бу шифокор қандай ёрдам беради / йўналиши нима" деса — МУТАХАССИСЛИГИ ва тажрибасига таяниб аниқ жавоб бер (мас. кардиолог → юрак, қон босими, ЭКГ; дерматолог → тери, соч ва ҳ.к.).
3. МУТАХАССИСЛИК МОСЛИГИ (энг муҳим): бемор муаммоси шифокор МУТАХАССИСЛИГИГА мос бўлса — тарифни ишонч билан ФАОЛ таклиф қил: НОМИ, НАРХИ ва нимани очишини (тўғридан-тўғри ёзишма, видео қўнғироқ, даволаш режаси) айт + аниқ чақирув: "Ҳозироқ «<тариф номи>»ни фаоллаштиринг". МОС БЎЛМАСА (мас. аллергологга бош оғриғи, кардиологга тери муаммоси) — ҲАЛОЛ бўл: бу шифокорнинг асосий йўналиши эмаслигини айт, қайси мутахассис мос келишини эслат (мас. невролог/терапевт) ва бу шифокорни фақат умумий/бошланғич маслаҳат учун юмшоқ тилга ол. Мос келмаган муаммога тарифни МАЖБУРЛАБ сотма, ошириб мақтама, алдама.
4. Мос бўлганда эътирозга ишонч билан жавоб бер: фойда, тажриба/рейтинг, нарх арзонлигини таъкидла, юмшоқ шоширтир. Лекин ҳалолликни ҲЕЧ ҚАЧОН бузма.
5. Илиқ, жонли, ишончли бўл — қуруқ/такрорий бўлма. ҲЕЧ ҚАЧОН тиббий ташхис қўйма ёки дори белгиламА (бу — айнан шифокорга ёзилишнинг сабаби).
6. Жавоб қисқа: 3-5 жумла. Охирида битта қисқа дисклеймер."""


def _norm(lang: str) -> str:
    if lang == "ru":
        return "ru"
    if lang in ("cyr", "uz-cyrl"):
        return "uz-cyrl"
    return "uz"


def _rules(lang: str) -> str:
    n = _norm(lang)
    if n == "ru":
        return _RULES_RU
    if n == "uz-cyrl":
        return _RULES_UZ_CYRL
    return _RULES_UZ


def _features_text(features, lang: str) -> str:
    if not isinstance(features, dict):
        return ""
    items = features.get(lang) or features.get("uz") or features.get("ru") or []
    if not isinstance(items, list):
        return ""
    return ", ".join(str(x) for x in items[:4])


def build_doctor_summary(doctor, lang: str) -> str:
    """Shifokor profili — AI javoblarda foydalanish uchun (mutaxassislik, tajriba, reyting, bio)."""
    parts = []
    # Barcha mutaxassisliklar (bir nechta bo'lishi mumkin); bo'lmasa asosiy `specialty`.
    spec_names = []
    try:
        for sp in doctor.specialties.all():
            nm = getattr(sp, "name", None)
            nm = pick_translation(nm, lang) if isinstance(nm, dict) else nm
            if nm:
                spec_names.append(nm)
    except Exception:
        pass
    if not spec_names:
        spec = getattr(doctor, "specialty", None)
        if spec is not None:
            nm = getattr(spec, "name", None)
            nm = pick_translation(nm, lang) if isinstance(nm, dict) else nm
            if nm:
                spec_names.append(nm)
    if spec_names:
        parts.append(f"Mutaxassisligi: {', '.join(spec_names)}")
    years = getattr(doctor, "experience_years", 0) or 0
    if years:
        parts.append(f"Tajriba: {years} yil")
    workplace = (getattr(doctor, "workplace", "") or "").strip()
    if workplace:
        parts.append(f"Ish joyi: {workplace}")
    try:
        reviews = doctor.total_reviews
        if reviews:
            parts.append(f"Reyting: {doctor.rating}/5 ({reviews} ta sharh)")
    except Exception:
        pass
    bio = (getattr(doctor, "bio", "") or "").strip()
    if bio:
        parts.append(f"Haqida: {bio[:400]}")
    if not parts:
        return "Profil ma'lumoti cheklangan — shifokorning tajribasi va xizmatlariga umumiy urg'u ber."
    return "\n".join(f"- {p}" for p in parts)


def build_tariff_summary(tariffs, lang: str) -> str:
    """Sotiladigan takliflar qisqacha (narx + muddat + imkoniyatlar).

    Duck-typed: features/final_price bo'lmasa e'tiborsiz qoldiriladi.
    """
    lines = []
    for t in tariffs:
        name = pick_translation(t.name, lang) or "Tarif"
        try:
            price = t.final_price
        except Exception:
            price = t.price
        line = f"- {name}: {price} so'm"
        duration = getattr(t, "duration_days", None)
        if duration:
            line += f" / {duration} kun"
        feats = _features_text(getattr(t, "features", None), lang)
        if feats:
            line += f" (imkoniyatlar: {feats})"
        desc = getattr(t, "description", None)
        if not feats and isinstance(desc, dict):
            d = pick_translation(desc, lang)
            if d:
                line += f" ({str(d)[:120]})"
        lines.append(line)
    return "\n".join(lines)


def build_chat_ai_system_prompt(lang: str, patient_context: str, doctor, tariffs) -> str:
    """AI gatekeeper system instruction (shifokor profili + tariflar + bemor konteksti)."""
    doctor_name = getattr(getattr(doctor, "user", None), "full_name", None) or "Shifokor"
    disclaimer = CHAT_AI_DISCLAIMER.get(_norm(lang), CHAT_AI_DISCLAIMER["uz"])
    doctor_summary = build_doctor_summary(doctor, lang)
    tariff_summary = build_tariff_summary(tariffs, lang)
    return (
        f"{DIET_CHAT_LANG_DIRECTIVE}\n\n"
        f"{_rules(lang)}\n\n"
        f"SHIFOKOR: {doctor_name}\n"
        f"SHIFOKOR MA'LUMOTI (savollarga javobда va sotuvda ayni shundan foydalan):\n{doctor_summary}\n\n"
        f"SOTILADIGAN TARIFLAR (nomi va narxi bilan FAOL taklif qil):\n{tariff_summary}\n\n"
        f"DISCLAIMER (har javob oxirida qisqa bir jumla):\n{disclaimer}\n\n"
        f"---\nBEMOR MA'LUMOTLARI:\n{patient_context}"
    )
