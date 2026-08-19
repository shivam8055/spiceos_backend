from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class DeliveryAgent(Base):
    __tablename__ = "delivery_agents"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(String, ForeignKey("restaurants.restaurant_id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    phone = Column(String(40), nullable=True)
    status = Column(String(20), nullable=False, default="offline", index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DeliveryJob(Base):
    __tablename__ = "delivery_jobs"

    id = Column(Integer, primary_key=True)
    delivery_token = Column(String(64), unique=True, nullable=False, default=lambda: uuid4().hex + uuid4().hex[:32], index=True)
    restaurant_id = Column(String, ForeignKey("restaurants.restaurant_id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True, index=True)
    agent_id = Column(Integer, ForeignKey("delivery_agents.id"), nullable=True, index=True)
    provider = Column(String(40), nullable=False, default="own_agent")
    provider_delivery_id = Column(String(120), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="created", index=True)
    pickup_address = Column(Text, nullable=True)
    delivery_address = Column(Text, nullable=False)
    customer_name = Column(String(120), nullable=True)
    customer_phone = Column(String(40), nullable=True)
    eta_minutes = Column(Integer, nullable=True)
    latitude = Column(String(32), nullable=True)
    longitude = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"

    id = Column(Integer, primary_key=True)
    delivery_job_id = Column(Integer, ForeignKey("delivery_jobs.id"), nullable=False, index=True)
    restaurant_id = Column(String, nullable=False, index=True)
    status = Column(String(30), nullable=False)
    actor_type = Column(String(30), nullable=False)
    actor_id = Column(String(120), nullable=True)
    latitude = Column(String(32), nullable=True)
    longitude = Column(String(32), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
