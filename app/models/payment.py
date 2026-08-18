from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider_order_id", name="uq_payments_provider_order_id"),
        UniqueConstraint("provider_payment_id", name="uq_payments_provider_payment_id"),
        UniqueConstraint("webhook_event_id", name="uq_payments_webhook_event_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, default="razorpay")
    provider_order_id = Column(String, nullable=False, index=True)
    provider_payment_id = Column(String, nullable=True, index=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    status = Column(String, nullable=False, default="created", index=True)
    provider_status = Column(String, nullable=True)
    webhook_event_id = Column(String, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    captured_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)
