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
from app.services.payment_service import create_qr_payment, process_webhook, verify_checkout_signature


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


def test_create_qr_payment_uses_server_total(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    db = make_db()
    order = Order(
        order_number="QR-TEST-002",
        restaurant_id="restaurant-1",
        customer_name="QR Guest",
        total=249.0,
        status="created",
        payment_status="pending",
        order_source="qr_table",
        qr_table_id=1,
        public_token_hash="token-hash-2",
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "order_RAZORPAY_NEW", "amount": 24900, "currency": "INR", "status": "created"}

    def fake_post(url, json, auth, timeout):
        assert url.endswith("/orders")
        assert json["amount"] == 24900
        assert json["currency"] == "INR"
        assert auth == ("rzp_test_key", "rzp_test_secret")
        assert timeout == 10.0
        return FakeResponse()

    monkeypatch.setattr(payment_service.httpx, "post", fake_post)
    response = create_qr_payment(db, order)

    assert response["provider_order_id"] == "order_RAZORPAY_NEW"
    assert response["amount_paise"] == 24900
    assert db.query(Payment).one().amount_paise == 24900


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


def test_paid_checkout_callback_is_idempotent_but_still_authenticated(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(payment_service, "RAZORPAY_KEY_SECRET", "rzp_test_secret")
    db = make_db()
    order, payment = seed_order(db)
    provider_payment_id = "pay_RAZORPAY123"
    payment.provider_payment_id = provider_payment_id
    payment.status = "paid"
    order.payment_status = "paid"
    db.commit()

    message = f"{payment.provider_order_id}|{provider_payment_id}".encode()
    signature = hmac.new(b"rzp_test_secret", message, hashlib.sha256).hexdigest()
    result = verify_checkout_signature(db, order, payment.provider_order_id, provider_payment_id, signature)
    assert result.id == payment.id
    assert result.status == "paid"

    other_payment_id = "pay_other"
    other_message = f"{payment.provider_order_id}|{other_payment_id}".encode()
    other_signature = hmac.new(b"rzp_test_secret", other_message, hashlib.sha256).hexdigest()
    try:
        verify_checkout_signature(db, order, payment.provider_order_id, other_payment_id, other_signature)
        assert False, "paid callback must not bind a different payment ID"
    except HTTPException as exc:
        assert exc.status_code == 409

    try:
        verify_checkout_signature(db, order, payment.provider_order_id, provider_payment_id, "invalid")
        assert False, "paid callback must still validate its signature"
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


def test_failed_webhook_marks_payment_failed_without_marking_order_paid(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    db = make_db()
    order, payment = seed_order(db)
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RAZORPAY_FAILED",
                    "order_id": payment.provider_order_id,
                    "amount": 24900,
                    "currency": "INR",
                    "status": "failed",
                    "error_description": "Payment declined in test mode",
                }
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"webhook_secret", raw, hashlib.sha256).hexdigest()

    process_webhook(db, raw, signature, "evt_failed_001")

    db.refresh(order)
    db.refresh(payment)
    assert payment.status == "failed"
    assert payment.provider_payment_id == "pay_RAZORPAY_FAILED"
    assert payment.last_error == "Payment declined in test mode"
    assert order.payment_status == "pending"


def test_refund_webhook_marks_order_refunded(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    db = make_db()
    order, payment = seed_order(db)
    payment.provider_payment_id = "pay_RAZORPAY123"
    payment.status = "paid"
    order.payment_status = "paid"
    db.commit()
    payload = {
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_123",
                    "payment_id": payment.provider_payment_id,
                    "amount": 24900,
                    "status": "processed",
                }
            }
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"webhook_secret", raw, hashlib.sha256).hexdigest()

    process_webhook(db, raw, signature, "evt_refund_001")

    db.refresh(order)
    db.refresh(payment)
    assert order.payment_status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_at is not None


def test_invalid_webhook_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(payment_service, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    db = make_db()
    try:
        process_webhook(db, b"{}", "invalid", "evt_invalid")
        assert False, "invalid webhook signature must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 400


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
