import hashlib
import hmac
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.order import Order
from app.models.payment import Payment
from app.services import razorpay_payment_service as service


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_order(db):
    order = Order(
        order_number="SP-1001",
        customer_name="Customer",
        total=499.0,
        order_source="qr_table",
        public_token_hash="public-hash",
        payment_status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_failed_payment_attempt_can_be_retried(monkeypatch):
    db = make_db()
    order = make_order(db)
    monkeypatch.setattr(service, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(service, "RAZORPAY_KEY_SECRET", "secret")

    provider_orders = iter([
        {"id": "order_old", "amount": 49900, "currency": "INR", "status": "created"},
        {"id": "order_new", "amount": 49900, "currency": "INR", "status": "created"},
    ])
    monkeypatch.setattr(service.httpx, "post", lambda *args, **kwargs: FakeResponse(next(provider_orders)))

    first = service.create_qr_payment(db, order)
    assert first["provider_order_id"] == "order_old"
    db.query(Payment).filter(Payment.provider_order_id == "order_old").one().status = "failed"
    db.commit()

    second = service.create_qr_payment(db, order)
    assert second["provider_order_id"] == "order_new"
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 2


def test_active_payment_attempt_is_reused(monkeypatch):
    db = make_db()
    order = make_order(db)
    monkeypatch.setattr(service, "RAZORPAY_KEY_ID", "rzp_test")
    monkeypatch.setattr(service, "RAZORPAY_KEY_SECRET", "secret")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(True)
        return FakeResponse({"id": "order_active", "amount": 49900, "currency": "INR", "status": "created"})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    first = service.create_qr_payment(db, order)
    second = service.create_qr_payment(db, order)

    assert first["provider_order_id"] == "order_active"
    assert second["provider_order_id"] == "order_active"
    assert len(calls) == 1


def test_partial_refund_does_not_mark_order_fully_refunded(monkeypatch):
    db = make_db()
    order = make_order(db)
    order.payment_status = "paid"
    payment = Payment(
        order_id=order.id,
        provider="razorpay",
        provider_order_id="order_paid",
        provider_payment_id="pay_123",
        amount_paise=49900,
        currency="INR",
        status="paid",
    )
    db.add(payment)
    db.commit()

    monkeypatch.setattr(service, "RAZORPAY_WEBHOOK_SECRET", "webhook-secret")
    body = json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"payment_id": "pay_123", "amount": 10000, "status": "processed"}}},
    }).encode()
    signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    service.process_webhook(db, body, signature, "evt_partial")

    db.refresh(order)
    db.refresh(payment)
    assert order.payment_status == "paid"
    assert payment.status == "paid"
    assert payment.refunded_at is None


def test_full_refund_marks_order_refunded(monkeypatch):
    db = make_db()
    order = make_order(db)
    order.payment_status = "paid"
    payment = Payment(
        order_id=order.id,
        provider="razorpay",
        provider_order_id="order_paid",
        provider_payment_id="pay_456",
        amount_paise=49900,
        currency="INR",
        status="paid",
    )
    db.add(payment)
    db.commit()

    monkeypatch.setattr(service, "RAZORPAY_WEBHOOK_SECRET", "webhook-secret")
    body = json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"payment_id": "pay_456", "amount": 49900, "status": "processed"}}},
    }).encode()
    signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

    service.process_webhook(db, body, signature, "evt_full")

    db.refresh(order)
    db.refresh(payment)
    assert order.payment_status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_at is not None
