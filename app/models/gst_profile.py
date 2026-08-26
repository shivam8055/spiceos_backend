from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class GSTProfile(Base):
    __tablename__ = "gst_profiles"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(String, nullable=False, unique=True, index=True)
    legal_name = Column(String, nullable=False, default="")
    trade_name = Column(String, nullable=False, default="")
    gstin = Column(String(15), nullable=True)
    pan = Column(String(10), nullable=True)
    business_type = Column(String(50), nullable=False, default="Proprietorship")
    state = Column(String(100), nullable=False, default="Bihar")
    state_code = Column(String(2), nullable=False, default="10")
    address = Column(Text, nullable=True)
    pincode = Column(String(6), nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    filing_frequency = Column(String(30), nullable=False, default="Monthly")
    composition_scheme = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
