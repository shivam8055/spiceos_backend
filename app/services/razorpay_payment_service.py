import hashlib
import hmac
import json
import logging
from datetime import datetime

import httpx
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET
from app.models.order import Order
from app.models.payment import Payment

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"
logger = logging.getLogger(__name__)


def _require_credentials() -> None:
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Online payments are not configured.")


def payment_response(payment: Payment, order: Order) -> dict:
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "payment_id": payment.id,
        "provider": payment.provider,
        "provider_order_id": payment.provider_order_id,
        "amount_paise": payment.amount_paise,
        "currency": payment.currency,
        "key_id": RAZORPAY_KEY_ID,
        "status": payment.status,
    }


def create_qr_payment(db: Session, order: Order) -> dict:
    _require_credentials()
    if order.order_source != "qr_table" or order.public_token_hash is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Online payment is only available for QR orders.")
    if order.payment_status == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has already been paid.")
    if order.payment_status == "refunded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has already been refunded.")

    existing = db.query(Payment).filter(Payment.order_id == order.id).first()
    if existing is not None:
        return payment_response(existing, order)

    amount_paise = int(round(float(order.total) * 100))
    if amount_paise <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Order total must be greater than zero for online payment.")

    # Razorpay's Orders API does not accept a `capture` field. Capture is
    # controlled by the Razorpay payment/order configuration and webhook flow.
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": order.order_number,
        "notes": {"spiceos_order_id": str(order.id)},
    }
    try:
        response = httpx.post(
            f"{RAZORPAY_BASE_URL}/orders",
            json=payload,
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            timeout=10.0,
        )
        response.raise_for_status()
        provider_order = response.json()
    except httpx.HTTPStatusError as exc:
        response = exc.response
        logger.error(
            "Razorpay order creation failed: status=%s body=%s",
            response.status_code,
            response.text[:1000],
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to create the payment order.") from exc
    except httpx.RequestError as exc:
        logger.error("Razorpay connection failed: %s", str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach payment provider.") from exc
    except ValueError as exc:
        logger.error("Razorpay returned invalid JSON: %s", str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment provider returned an invalid response.") from exc

    provider_order_id = provider_order.get("id")
    if not provider_order_id or provider_order.get("amount") != amount_paise or provider_order.get("currency") != "INR":
        logger.error(
            "Razorpay returned invalid order: id=%s amount=%s currency=%s expected_amount=%s",
            provider_order_id,
            provider_order.get("amount"),
            provider_order.get("currency"),
            amount_paise,
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment provider returned an invalid order.")

    payment = Payment(
        order_id=order.id,
        provider="razorpay",
        provider_order_id=provider_order_id,
        amount_paise=amount_paise,
        currency="INR",
        status="created",
        provider_status=provider_order.get("status"),
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Payment).filter(Payment.order_id == order.id).first()
        if existing is None:
            raise
        return payment_response(existing, order)
    db.refresh(payment)
    return payment_response(payment, order)


def verify_checkout_signature(db: Session, order: Order, provider_order_id: str, provider_payment_id: str, signature: str) -> Payment:
    _require_credentials()
    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    if payment is None or payment.provider_order_id != provider_order_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment order not found.")
    if payment.provider != "razorpay":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unsupported payment provider.")

    # The Razorpay webhook is authoritative for capture. The checkout callback
    # can arrive after the webhook, so a repeated verify request must be
    # idempotent instead of returning 409 after the order is already paid.
    if order.payment_status == "paid":
        return payment
    if order.payment_status == "refunded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has already been refunded.")

    message = f"{payment.provider_order_id}|{provider_payment_id}".encode("utf-8")
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment signature.")

    # Razorpay permits multiple attempts against one order. Until the order is
    # captured, bind the latest verified payment attempt to this local record.
    payment.provider_payment_id = provider_payment_id
    payment.status = "verified"
    payment.provider_status = "signature_verified"
    db.commit()
    db.refresh(payment)
    return payment


def verify_webhook_signature(raw_body: bytes, signature: str) -> None:
    if not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Payment webhooks are not configured.")
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature.")


def process_webhook(db: Session, raw_body: bytes, signature: str, event_id: str) -> None:
    verify_webhook_signature(raw_body, signature)
    if not event_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing webhook event ID.")
    if db.query(Payment).filter(Payment.webhook_event_id == event_id).first() is not None:
        return

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload.") from exc

    event = payload.get("event")
    payload_root = payload.get("payload") or {}
    payment_entity = (payload_root.get("payment") or {}).get("entity") or {}
    refund_entity = (payload_root.get("refund") or {}).get("entity") or {}

    if event in {"refund.processed", "payment.refunded"}:
        provider_payment_id = refund_entity.get("payment_id")
        payment = db.query(Payment).filter(Payment.provider_payment_id == provider_payment_id).first() if provider_payment_id else None
        if payment is None:
            return
        amount = int(refund_entity.get("amount", 0))
        if amount <= 0 or amount > payment.amount_paise:
            payment.last_error = "Provider refund amount was invalid."
            db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid refund amount.")
        payment.provider_status = refund_entity.get("status") or event
        payment.webhook_event_id = event_id
        payment.status = "refunded"
        payment.refunded_at = payment.refunded_at or datetime.utcnow()
        order = db.query(Order).filter(Order.id == payment.order_id).first()
        if order is not None:
            order.payment_status = "refunded"
        db.commit()
        return

    provider_order_id = payment_entity.get("order_id")
    provider_payment_id = payment_entity.get("id")
    if not event or not provider_order_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook is missing payment identifiers.")

    payment = db.query(Payment).filter(Payment.provider_order_id == provider_order_id).first()
    if payment is None:
        return
    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if order is None:
        payment.last_error = "Associated order no longer exists."
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Associated order not found.")

    if payment_entity.get("currency") != payment.currency or int(payment_entity.get("amount", -1)) != payment.amount_paise:
        payment.last_error = "Provider amount or currency did not match the local payment."
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment amount or currency mismatch.")

    if order.payment_status == "paid" and event in {"payment.captured", "order.paid"}:
        return

    payment.provider_payment_id = provider_payment_id or payment.provider_payment_id
    payment.provider_status = payment_entity.get("status")
    payment.webhook_event_id = event_id

    now = datetime.utcnow()
    if event in {"payment.captured", "order.paid"}:
        payment.status = "paid"
        payment.captured_at = payment.captured_at or now
        order.payment_status = "paid"
    elif event == "payment.failed":
        payment.status = "failed"
        payment.last_error = (payment_entity.get("error_description") or payment_entity.get("error_reason") or "Payment failed")[:1000]
    else:
        payment.status = payment.status or "created"

    db.commit()
