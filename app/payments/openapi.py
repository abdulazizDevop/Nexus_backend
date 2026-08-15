"""drf-spectacular postprocessing hook — paytechuz webhook URL'larini
schema'ga qo'lda qo'shadi.

Sabab: paytechuz `BaseXxxWebhookView` lar oddiy Django `View` (DRF emas), shuning
uchun avtomatik introspection ularni topa olmaydi. Lekin hujjatlash uchun ular
Swagger'da ko'rinishi kerak — manual path'lar bilan ta'minlaymiz.
"""

WEBHOOK_PATHS = {
    "/api/v1/payments/webhook/payme/": {
        "post": {
            "operationId": "v1_payments_webhook_payme_create",
            "tags": ["Payments - Webhook"],
            "summary": "Payme callback (server-to-server)",
            "description": (
                "Payme tomonidan chaqiriladigan JSON-RPC webhook. Authorization: "
                "Basic base64('Paycom:PAYME_KEY'). Frontend chaqirmasin — paytechuz "
                "signature'ni tekshiradi, muvaffaqiyatli to'lovda Payment yakunlanadi "
                "va ProSubscription yoki DoctorTariffPurchase yaratiladi."
            ),
            "security": [{"BasicAuth": []}],
            "responses": {"200": {"description": "JSON-RPC result/error"}},
        }
    },
    "/api/v1/payments/webhook/click/": {
        "post": {
            "operationId": "v1_payments_webhook_click_create",
            "tags": ["Payments - Webhook"],
            "summary": "Click callback (server-to-server)",
            "description": (
                "Click tomonidan chaqiriladigan webhook (Prepare/Complete). "
                "Frontend chaqirmasin — paytechuz signature tekshiradi."
            ),
            "responses": {"200": {"description": "Click response"}},
        }
    },
}


def add_webhook_paths(result, generator, request, public):  # noqa: ARG001
    """Generated schema'ga webhook path'larini qo'shadi."""
    paths = result.setdefault("paths", {})
    for path, methods in WEBHOOK_PATHS.items():
        paths.setdefault(path, {}).update(methods)
    return result
