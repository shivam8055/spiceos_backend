from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, nullable=False)
    restaurant_id = Column(String, nullable=True, index=True)
    customer_id = Column(String, nullable=True, index=True)
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=True)
    primary_item = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow, index=True)
    status = Column(String, nullable=True, default="created", index=True)
    payment_status = Column(String, nullable=True, default="pending")
    total = Column(Float, nullable=False)
    order_source = Column(String, nullable=True, default="Unknown")
    qr_table_id = Column(Integer, nullable=True, index=True)
    qr_session_id = Column(String, nullable=True, index=True)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    public_token_hash = Column(String, unique=True, nullable=True, index=True)
