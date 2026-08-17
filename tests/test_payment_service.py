import hashlib
import hmac
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.order import Order
from app.models.payment import Payment
from app.services import payment_service
from app.services.payment_service import process_webhook, verify_checkout_signature


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed_order(db):
    order = Order(
        order_number="QR-TEST-001",
        restaurant_id="restaurant-1",
        customer_name="QR Guest",
        total=249.0,
        status="created",
        payment_status="pending",
        order_source="qr_table",
        qr_table_id=1,
        public_token_hash="token-hash",
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    payment = Payment(
        order_id=order.id,
        provider="razorpay",
        provider_order_id="order_RAZORPAY123",
        amount_paise=24900,
        currency="INR",
        status="created",
        provider_status="created",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return order, payment


def test_checkout_signature_verification_binds_payment(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    db = make_db()
    order, payment = seed_order(db)
    provider_payment_id = "pay_RAZORPAY123"
    message = f"{payment.provider_order_id}|{provider_payment_id}".encode()
    signature = hmac.new(b"rzp_test_secret", message, hashlib.sha256).hexdigest()

    verified = verify_checkout_signature(db, order, payment.provider_order_id, provider_payment_id, signature)

    assert verified.status == "verified"
    assert verified.provider_payment_id == provider_payment_id
    assert order.payment_status == "pending"


def test_invalid_checkout_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    db = make_db()
    order, payment = seed_order(db)
    try:
        verify_checkout_signature(db, order, payment.provider_order_id, "pay_bad", "invalid")
        assert False, "invalid payment signature must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_captured_webhook_marks_order_paid_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    db = make_db()
    order, payment = seed_order(db)
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RAZORPAY123",
                    "order_id": payment.provider_order_id,
                    "amount": 24900,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"webhook_secret", raw, hashlib.sha256).hexdigest()

    process_webhook(db, raw, signature, "evt_001")
    process_webhook(db, raw, signature, "evt_001")

    db.refresh(order)
    db.refresh(payment)
    assert order.payment_status == "paid"
    assert payment.status == "paid"
    assert payment.provider_payment_id == "pay_RAZORPAY123"
    assert payment.webhook_event_id == "evt_001"


def test_webhook_amount_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    db = make_db()
    order, payment = seed_order(db)
    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RAZORPAY123",
                    "order_id": payment.provider_order_id,
                    "amount": 25000,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"webhook_secret", raw, hashlib.sha256).hexdigest()

    try:
        process_webhook(db, raw, signature, "evt_bad_amount")
        assert False, "provider amount mismatch must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 409

    db.refresh(order)
    assert order.payment_status == "pending"
