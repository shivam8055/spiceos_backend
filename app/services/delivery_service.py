from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.delivery import DeliveryAgent, DeliveryEvent, DeliveryJob
from app.models.order import Order

VALID_AGENT_STATUS = {"offline", "available", "busy"}
VALID_DELIVERY_STATUS = {"created", "dispatching", "assigned", "picked_up", "out_for_delivery", "delivered", "cancelled", "failed"}
TRANSITIONS = {
    "created": {"dispatching", "cancelled", "failed"},
    "dispatching": {"assigned", "cancelled", "failed"},
    "assigned": {"picked_up", "cancelled", "failed"},
    "picked_up": {"out_for_delivery", "cancelled", "failed"},
    "out_for_delivery": {"delivered", "cancelled", "failed"},
    "delivered": set(),
    "cancelled": set(),
    "failed": {"dispatching", "cancelled"},
}


def _event(db: Session, job: DeliveryJob, status: str, actor_type: str, actor_id: Optional[str] = None, **kwargs):
    db.add(DeliveryEvent(delivery_job_id=job.id, restaurant_id=job.restaurant_id, status=status, actor_type=actor_type, actor_id=actor_id, **kwargs))


def create_delivery(db: Session, restaurant_id: str, payload) -> DeliveryJob:
    order = db.query(Order).filter(Order.id == payload.order_id, Order.restaurant_id == restaurant_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    existing = db.query(DeliveryJob).filter(DeliveryJob.order_id == order.id, DeliveryJob.restaurant_id == restaurant_id).first()
    if existing:
        return existing
    job = DeliveryJob(restaurant_id=restaurant_id, order_id=order.id, delivery_address=payload.delivery_address, pickup_address=payload.pickup_address, customer_name=payload.customer_name, customer_phone=payload.customer_phone, provider="own_agent", status="created")
    db.add(job)
    db.flush()
    _event(db, job, "created", "system")
    db.commit()
    db.refresh(job)
    return job


def assign_delivery(db: Session, restaurant_id: str, delivery_id: int, agent_id: int) -> DeliveryJob:
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == restaurant_id).first()
    agent = db.query(DeliveryAgent).filter(DeliveryAgent.id == agent_id, DeliveryAgent.restaurant_id == restaurant_id, DeliveryAgent.is_active.is_(True)).first()
    if not job or not agent:
        raise HTTPException(status_code=404, detail="Delivery or agent not found")
    if agent.status not in {"available", "busy"}:
        raise HTTPException(status_code=409, detail="Agent is not available")
    if job.status not in {"created", "dispatching", "failed"}:
        raise HTTPException(status_code=409, detail="Delivery cannot be assigned in its current state")
    if job.status != "assigned":
        job.status = "assigned"
        _event(db, job, "assigned", "staff", str(agent.id))
    job.agent_id = agent.id
    agent.status = "busy"
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def update_status(db: Session, restaurant_id: str, delivery_id: int, payload, actor_type="agent", actor_id=None) -> DeliveryJob:
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == restaurant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if payload.status not in VALID_DELIVERY_STATUS or payload.status not in TRANSITIONS.get(job.status, set()):
        raise HTTPException(status_code=409, detail=f"Invalid delivery transition: {job.status} -> {payload.status}")
    job.status = payload.status
    job.updated_at = datetime.utcnow()
    if payload.status in {"delivered", "cancelled", "failed"} and job.agent_id:
        agent = db.query(DeliveryAgent).filter(DeliveryAgent.id == job.agent_id, DeliveryAgent.restaurant_id == restaurant_id).first()
        if agent:
            agent.status = "available" if payload.status == "delivered" else agent.status
    _event(db, job, payload.status, actor_type, actor_id, note=payload.note, latitude=payload.latitude, longitude=payload.longitude)
    db.commit()
    db.refresh(job)
    return job


def update_location(db: Session, restaurant_id: str, delivery_id: int, payload) -> DeliveryJob:
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == restaurant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Delivery not found")
    job.latitude, job.longitude, job.updated_at = payload.latitude, payload.longitude, datetime.utcnow()
    _event(db, job, job.status, "agent", str(job.agent_id) if job.agent_id else None, latitude=payload.latitude, longitude=payload.longitude)
    db.commit()
    db.refresh(job)
    return job
