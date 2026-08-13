from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    sku = Column(String, unique=True, nullable=True, index=True)
    unit = Column(String, nullable=False, default="unit")
    quantity = Column(Float, nullable=False, default=0)
    reorder_level = Column(Float, nullable=False, default=0)
    cost_per_unit = Column(Float, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
