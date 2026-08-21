import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.delivery import DeliveryEvent, DeliveryJob
from app.models.order import Order

router = APIRouter(prefix="/webhooks/delivery", tags=["delivery-webhooks"])

UBER_STATUS_MAP = {
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


def _verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _extract(payload: dict):
    data = payload.get("data") or {}
    meta = payload.get("meta") or {}
    provider_delivery_id = data.get("id") or meta.get("order_id") or meta.get("delivery_id")
    status = data.get("status") or meta.get("status")
    event_id = payload.get("event_id") or payload.get("id")
    return str(provider_delivery_id) if provider_delivery_id else None, str(status) if status else None, str(event_id) if event_id else None, data


def _apply(db: Session, provider: str, payload: dict) -> None:
    provider_delivery_id, provider_status, event_id, data = _extract(payload)
    if not provider_delivery_id or not provider_status:
        raise HTTPException(status_code=400, detail="Webhook is missing delivery id or status")
    job = db.query(DeliveryJob).filter(
        DeliveryJob.provider == provider,
        DeliveryJob.provider_delivery_id == provider_delivery_id,
    ).first()
    if not job:
        return
    if event_id and db.query(DeliveryEvent).filter(
        DeliveryEvent.delivery_job_id == job.id,
        DeliveryEvent.actor_type == "provider",
        DeliveryEvent.actor_id == event_id,
    ).first():
        return

    next_status = UBER_STATUS_MAP.get(provider_status)
    if next_status:
        job.status = next_status
    courier = data.get("courier") or {}
    location = courier.get("location") or data.get("location") or {}
    if location.get("lat") is not None:
        job.latitude = str(location.get("lat"))
    if location.get("lng") is not None:
        job.longitude = str(location.get("lng"))
    if data.get("tracking_url"):
        job.tracking_url = data["tracking_url"]

    db.add(DeliveryEvent(
        delivery_job_id=job.id,
        restaurant_id=job.restaurant_id,
        status=job.status,
        actor_type="provider",
        actor_id=event_id or provider_delivery_id,
        latitude=job.latitude,
        longitude=job.longitude,
        note=f"{provider} webhook status: {provider_status}",
    ))

    order = db.query(Order).filter(Order.id == job.order_id, Order.restaurant_id == job.restaurant_id).first()
    if order:
        if job.status in {"picked_up", "out_for_delivery"} and order.status == "ready":
            order.status = "outForDelivery"
        elif job.status == "delivered" and order.status == "outForDelivery":
            order.status = "delivered"
        elif job.status == "cancelled" and order.status not in {"delivered", "cancelled"}:
            order.status = "cancelled"

    db.commit()


@router.post("/uber")
async def uber_webhook(
    request: Request,
    x_uber_signature: str | None = Header(default=None),
    x_postmates_signature: str | None = Header(default=None),
):
    body = await request.body()
    secret = os.getenv("UBER_DIRECT_WEBHOOK_SECRET")
    signature = x_uber_signature or x_postmates_signature
    if not _verify_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid Uber webhook signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload") from exc
    db: Session = SessionLocal()
    try:
        _apply(db, "uber_direct", payload)
    finally:
        db.close()
    return {}
