from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.delivery import DeliveryAgent, DeliveryEvent, DeliveryJob
from app.models.order import Order
from app.services.delivery_providers import OwnAgentProvider
from app.services.external_delivery_providers import OlaProvider, ProviderNotConfigured, ProviderRequestError, RapidoProvider, UberDirectProvider

VALID_AGENT_STATUS = {"offline", "available", "busy"}
VALID_DELIVERY_STATUS = {"created", "dispatching", "assigned", "picked_up", "out_for_delivery", "delivered", "cancelled", "failed"}
VALID_PROVIDERS = {"own_agent", "uber_direct", "rapido", "ola"}
TRANSITIONS = {
    "created": {"dispatching", "cancelled", "failed"},
    "dispatching": {"assigned", "cancelled", "failed", "picked_up", "out_for_delivery"},
    "assigned": {"picked_up", "cancelled", "failed"},
    "picked_up": {"out_for_delivery", "cancelled", "failed"},
    "out_for_delivery": {"delivered", "cancelled", "failed"},
    "delivered": set(),
    "cancelled": set(),
    "failed": {"dispatching", "cancelled"},
}
EXTERNAL_STATUS_MAP = {
    "pending": "dispatching",
    "pickup": "assigned",
    "pickup_complete": "picked_up",
    "dropoff": "out_for_delivery",
    "delivered": "delivered",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "failed": "failed",
    "SCHEDULED": "dispatching",
    "EN_ROUTE_TO_PICKUP": "assigned",
    "ARRIVED_AT_PICKUP": "assigned",
    "EN_ROUTE_TO_DROPOFF": "out_for_delivery",
    "ARRIVED_AT_DROPOFF": "out_for_delivery",
    "COMPLETED": "delivered",
    "FAILED": "failed",
}


def _event(db: Session, job: DeliveryJob, status: str, actor_type: str, actor_id: Optional[str] = None, **kwargs):
    db.add(DeliveryEvent(delivery_job_id=job.id, restaurant_id=job.restaurant_id, status=status, actor_type=actor_type, actor_id=actor_id, **kwargs))


def provider_for(name: str):
    if name == "own_agent":
        return OwnAgentProvider()
    if name == "uber_direct":
        return UberDirectProvider()
    if name == "rapido":
        return RapidoProvider()
    if name == "ola":
        return OlaProvider()
    raise HTTPException(status_code=422, detail=f"Unsupported delivery provider: {name}")


def create_delivery(db: Session, restaurant_id: str, payload) -> DeliveryJob:
    order = db.query(Order).filter(Order.id == payload.order_id, Order.restaurant_id == restaurant_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    existing = db.query(DeliveryJob).filter(DeliveryJob.order_id == order.id, DeliveryJob.restaurant_id == restaurant_id).first()
    if existing:
        return existing
    provider_name = payload.provider.lower()
    if provider_name not in VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported delivery provider")
    try:
        provider = provider_for(provider_name)
        provider_delivery_id = None
        eta_minutes = None
        tracking_url = None
        if provider_name != "own_agent":
            if not payload.pickup_address:
                raise HTTPException(status_code=422, detail="Pickup address is required for external delivery")
            result = provider.create_delivery(
                pickup_address=payload.pickup_address,
                delivery_address=payload.delivery_address,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                idempotency_key=f"spiceos-order-{order.id}",
            )
            provider_delivery_id = result.provider_delivery_id
            eta_minutes = result.eta_minutes
            tracking_url = result.tracking_url
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    job = DeliveryJob(
        restaurant_id=restaurant_id,
        order_id=order.id,
        delivery_address=payload.delivery_address,
        pickup_address=payload.pickup_address,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        provider=provider_name,
        provider_delivery_id=provider_delivery_id,
        tracking_url=tracking_url,
        eta_minutes=eta_minutes,
        status="dispatching" if provider_name != "own_agent" else "created",
    )
    db.add(job)
    db.flush()
    _event(db, job, job.status, "system", note=f"Provider: {provider_name}")
    db.commit()
    db.refresh(job)
    return job


def assign_delivery(db: Session, restaurant_id: str, delivery_id: int, agent_id: int) -> DeliveryJob:
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == restaurant_id).first()
    agent = db.query(DeliveryAgent).filter(DeliveryAgent.id == agent_id, DeliveryAgent.restaurant_id == restaurant_id, DeliveryAgent.is_active.is_(True)).first()
    if not job or not agent:
        raise HTTPException(status_code=404, detail="Delivery or agent not found")
    if job.provider != "own_agent":
        raise HTTPException(status_code=409, detail="External-provider deliveries cannot be assigned to an own agent")
    if agent.status not in {"available", "busy"}:
        raise HTTPException(status_code=409, detail="Agent is not available")
    if job.status not in {"created", "dispatching", "failed"}:
        raise HTTPException(status_code=409, detail="Delivery cannot be assigned in its current state")
    job.status = "assigned"
    job.agent_id = agent.id
    agent.status = "busy"
    job.updated_at = datetime.utcnow()
    _event(db, job, "assigned", "staff", str(agent.id))
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
            agent.status = "available"
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


def refresh_external_status(db: Session, restaurant_id: str, delivery_id: int) -> DeliveryJob:
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == restaurant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if job.provider == "own_agent" or not job.provider_delivery_id:
        return job
    try:
        result = provider_for(job.provider).get_status(job.provider_delivery_id)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=f"Provider status lookup failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Provider status lookup failed: {exc}") from exc

    next_status = EXTERNAL_STATUS_MAP.get(result.status)
    if next_status and next_status != job.status and next_status in TRANSITIONS.get(job.status, set()):
        job.status = next_status
        order = db.query(Order).filter(Order.id == job.order_id, Order.restaurant_id == restaurant_id).first()
        if order and next_status in {"picked_up", "out_for_delivery"} and order.status == "ready":
            order.status = "outForDelivery"
        elif order and next_status == "delivered" and order.status == "outForDelivery":
            order.status = "delivered"
    if result.tracking_url:
        job.tracking_url = result.tracking_url
    if result.eta_minutes is not None:
        job.eta_minutes = result.eta_minutes
    _event(db, job, job.status, "provider", job.provider, note=f"Provider status: {result.status}")
    db.commit()
    db.refresh(job)
    return job
