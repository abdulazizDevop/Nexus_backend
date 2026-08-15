"""Click webhook simulator — soxta karta topmasdan to'lov flow'ni test qilish.

Foydalanish:
    # Mavjud PENDING Payment ID bilan to'liq flow (Prepare → Complete):
    python manage.py simulate_click_webhook --payment 22

    # Faqat Prepare bosqichi (pre-payment validation):
    python manage.py simulate_click_webhook --payment 22 --prepare-only

    # Bekor qilish stsenariy (Cancel callback):
    python manage.py simulate_click_webhook --payment 22 --cancel

Click webhook signature formulasi rasmiy:
    md5(click_trans_id + service_id + secret_key + merchant_trans_id + amount + action + sign_time)

Bu test paytechuz security validation'ni o'tib, `_complete_payment` ga yetib boradi —
ya'ni haqiqiy Click sandbox to'lovi kelgandagi kabi ishlaydi.
"""

import hashlib
import json
from datetime import datetime
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.payments.models import Payment


CLICK_ACTION_PREPARE = 0
CLICK_ACTION_COMPLETE = 1


def _click_signature(
    click_trans_id: str,
    service_id: str,
    secret_key: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
    merchant_prepare_id: str = "",
) -> str:
    """Click sign_string formulasi (rasmiy docs.click.uz)."""
    raw = (
        f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}"
        f"{merchant_prepare_id}{amount}{action}{sign_time}"
    )
    # MD5 — Click sign_string protokoli MAJBURIY (docs.click.uz). Dev simulyator,
    # xavfsizlik-kritik hashing emas (CodeQL FP).
    return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324


class Command(BaseCommand):
    help = "Click webhook'ni simulyatsiya qilish — test karta yo'q paytida to'liq flow tekshiruv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--payment", type=int, required=True,
            help="Mavjud Payment ID (PENDING bo'lishi tavsiya etiladi)",
        )
        parser.add_argument(
            "--prepare-only", action="store_true",
            help="Faqat Prepare callback (Complete'siz)",
        )
        parser.add_argument(
            "--cancel", action="store_true",
            help="Cancel callback (action=1 + error=-9999 yoki o'xshash)",
        )
        parser.add_argument(
            "--url",
            default="http://127.0.0.1:8000/api/v1/payments/webhook/click/",
            help="Webhook URL (default: lokal)",
        )

    def handle(self, *args, **opts):
        payment_id = opts["payment"]
        webhook_url = opts["url"]

        try:
            payment = Payment.objects.get(id=payment_id)
        except Payment.DoesNotExist as exc:
            raise CommandError(f"Payment id={payment_id} topilmadi") from exc

        if payment.provider != "click":
            self.stdout.write(self.style.WARNING(
                f"Diqqat: Payment.provider='{payment.provider}', click emas"
            ))

        cfg = settings.PAYTECHUZ["CLICK"]
        service_id = str(cfg["SERVICE_ID"])
        secret_key = cfg["SECRET_KEY"]

        click_trans_id = f"sim-{payment.id}-{int(datetime.now().timestamp())}"
        merchant_trans_id = str(payment.id)
        amount = str(payment.amount)
        sign_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # === 1) PREPARE callback ===
        prepare_sign = _click_signature(
            click_trans_id, service_id, secret_key,
            merchant_trans_id, amount, str(CLICK_ACTION_PREPARE), sign_time,
        )
        prepare_data = {
            "click_trans_id": click_trans_id,
            "service_id": service_id,
            "merchant_trans_id": merchant_trans_id,
            "amount": amount,
            "action": CLICK_ACTION_PREPARE,
            "error": 0,
            "error_note": "Success",
            "sign_time": sign_time,
            "sign_string": prepare_sign,
            "click_paydoc_id": click_trans_id,
        }

        self.stdout.write(self.style.MIGRATE_HEADING("\n→ PREPARE webhook yuborilmoqda..."))
        self.stdout.write(f"  URL:      {webhook_url}")
        self.stdout.write(f"  Payment:  id={payment.id} amount={amount} status={payment.status}")
        self.stdout.write(f"  ClickTxn: {click_trans_id}")

        resp = requests.post(
            webhook_url,
            data=urlencode(prepare_data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        self.stdout.write(f"  HTTP:     {resp.status_code}")
        self.stdout.write(f"  Body:     {resp.text[:300]}")

        try:
            prepare_body = resp.json()
            error_code = prepare_body.get("error", "?")
            merchant_prepare_id = prepare_body.get("merchant_prepare_id", "")
        except (ValueError, json.JSONDecodeError):
            self.stdout.write(self.style.ERROR("  Javob JSON emas — paytechuz noto'g'ri javob qaytardi"))
            return

        if error_code != 0:
            self.stdout.write(self.style.ERROR(
                f"  ✗ Prepare xato: code={error_code} note={prepare_body.get('error_note')}"
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"  ✓ Prepare OK: merchant_prepare_id={merchant_prepare_id}"
        ))

        if opts["prepare_only"]:
            self.stdout.write("\nPrepare-only rejimi — Complete o'tkazilmadi.")
            return

        # === 2) COMPLETE callback ===
        complete_sign = _click_signature(
            click_trans_id, service_id, secret_key,
            merchant_trans_id, amount, str(CLICK_ACTION_COMPLETE), sign_time,
            merchant_prepare_id=str(merchant_prepare_id),
        )
        complete_data = {
            "click_trans_id": click_trans_id,
            "service_id": service_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": merchant_prepare_id,
            "amount": amount,
            "action": CLICK_ACTION_COMPLETE,
            "error": -9999 if opts["cancel"] else 0,
            "error_note": "Cancelled by user" if opts["cancel"] else "Success",
            "sign_time": sign_time,
            "sign_string": complete_sign,
            "click_paydoc_id": click_trans_id,
        }

        action_label = "CANCEL" if opts["cancel"] else "COMPLETE"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n→ {action_label} webhook yuborilmoqda..."))

        resp = requests.post(
            webhook_url,
            data=urlencode(complete_data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        self.stdout.write(f"  HTTP:     {resp.status_code}")
        self.stdout.write(f"  Body:     {resp.text[:300]}")

        try:
            body = resp.json()
            err = body.get("error", "?")
            if err == 0:
                self.stdout.write(self.style.SUCCESS(f"  ✓ {action_label} OK"))
            else:
                self.stdout.write(self.style.ERROR(
                    f"  ✗ {action_label} xato: code={err} note={body.get('error_note')}"
                ))
        except (ValueError, json.JSONDecodeError):
            self.stdout.write(self.style.ERROR("  Javob JSON emas"))

        # === Yakuniy tekshiruv ===
        payment.refresh_from_db()
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Natija ==="))
        self.stdout.write(f"  Payment.status:        {payment.status}")
        self.stdout.write(f"  Payment.provider_txn:  {payment.provider_transaction_id}")
        self.stdout.write(f"  Payment.completed_at:  {payment.completed_at}")

        if payment.purpose == Payment.Purpose.PRO_SUBSCRIPTION:
            from app.payments.models import ProSubscription
            sub = ProSubscription.objects.filter(payment=payment).first()
            self.stdout.write(f"  ProSubscription:       {sub or '(yaratilmagan)'}")
        elif payment.purpose == Payment.Purpose.DOCTOR_TARIFF:
            from app.payments.models import DoctorTariffPurchase
            purchase = DoctorTariffPurchase.objects.filter(payment=payment).first()
            self.stdout.write(f"  DoctorTariffPurchase:  {purchase or '(yaratilmagan)'}")
