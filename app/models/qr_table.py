from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class QRTable(Base):
    __tablename__ = "qr_tables"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(String, nullable=False, index=True)
    branch_id = Column(String, nullable=False, index=True)
    table_id = Column(String, nullable=False, index=True)
    table_name = Column(String, nullable=False)
    session_id = Column(String, nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
