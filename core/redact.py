"""PII maskalash — log'larga maxfiy ma'lumot ochiq tushmasligi uchun.

CodeQL "clear-text logging of sensitive information" alertlari uchun. Telefon/email
qisman maskalanadi: debug uchun identifikatsiya yetarli, lekin to'liq PII chiqmaydi.
"""


def mask_phone(phone) -> str:
    """+998901234567 -> +998****4567. Bo'sh/qisqa bo'lsa '***'."""
    s = str(phone or "").strip()
    if len(s) < 7:
        return "***"
    return f"{s[:4]}****{s[-4:]}"


def mask_email(email) -> str:
    """john@example.com -> j***@example.com. Bo'sh/noto'g'ri bo'lsa '—'."""
    s = str(email or "").strip()
    if not s or "@" not in s:
        return "—"
    local, _, domain = s.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}"
