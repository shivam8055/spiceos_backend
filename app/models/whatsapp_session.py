from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class WhatsAppSession(Base):
    __tablename__ = "whatsapp_sessions"

    id = Column(Integer, primary_key=True, index=True)
    wa_id = Column(String, nullable=False, unique=True, index=True)
    restaurant_id = Column(String, nullable=True, index=True)
    branch_id = Column(String, nullable=True, index=True)
    qr_token = Column(String, nullable=True)
    state = Column(String, nullable=False, default="awaiting_order")
    draft_json = Column(Text, nullable=False, default="{}")
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    last_message_id = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
