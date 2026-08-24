from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user, require_manager, require_staff
from app.models.delivery import DeliveryAgent, DeliveryEvent, DeliveryJob
from app.schemas.delivery import DeliveryAgentCreate, DeliveryAgentUpdate, DeliveryAssign, DeliveryCreate, DeliveryLocationUpdate, DeliveryQuoteRequest, DeliveryStatusUpdate
from app.services.delivery_service import VALID_PROVIDERS, assign_delivery, create_delivery, provider_for, refresh_external_status, update_location, update_status
from app.services.external_delivery_providers import ProviderNotConfigured, ProviderRequestError

router = APIRouter(prefix="/delivery", tags=["delivery"])


def restaurant_id_for(user):
    restaurant_id = getattr(user, "restaurant_id", None)
    if not restaurant_id:
        raise HTTPException(status_code=403, detail="Restaurant is not assigned")
    return restaurant_id


@router.get("/providers")
def list_providers():
    providers = []
    for name in sorted(VALID_PROVIDERS):
        configured = True
        reason = None
        try:
            provider_for(name)
        except Exception as exc:
            configured = False
            reason = str(exc)
        providers.append({"provider": name, "configured": configured, "reason": reason})
    return providers


@router.post("/quote")
def get_quote(payload: DeliveryQuoteRequest, user=Depends(require_staff)):
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported delivery provider")
    try:
        quote = provider_for(payload.provider).quote(payload.pickup_address, payload.delivery_address)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "provider": quote.provider,
        "amount": quote.amount,
        "currency": quote.currency,
        "eta_minutes": quote.eta_minutes,
    }


@router.get("/agents")
def list_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rid = restaurant_id_for(user)
    return db.query(DeliveryAgent).filter(DeliveryAgent.restaurant_id == rid).order_by(DeliveryAgent.id.desc()).all()


@router.post("/agents", status_code=201)
def create_agent(payload: DeliveryAgentCreate, db: Session = Depends(get_db), user=Depends(require_manager)):
    rid = restaurant_id_for(user)
    agent = DeliveryAgent(restaurant_id=rid, name=payload.name, phone=payload.phone, status="available")
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: int, payload: DeliveryAgentUpdate, db: Session = Depends(get_db), user=Depends(require_manager)):
    rid = restaurant_id_for(user)
    agent = db.query(DeliveryAgent).filter(DeliveryAgent.id == agent_id, DeliveryAgent.restaurant_id == rid).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if payload.status is not None and payload.status not in {"offline", "available", "busy"}:
        raise HTTPException(status_code=422, detail="Invalid agent status")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rid = restaurant_id_for(user)
    return db.query(DeliveryJob).filter(DeliveryJob.restaurant_id == rid).order_by(DeliveryJob.id.desc()).all()


@router.post("/jobs", status_code=201)
def create_job(payload: DeliveryCreate, db: Session = Depends(get_db), user=Depends(require_staff)):
    return create_delivery(db, restaurant_id_for(user), payload)


@router.post("/jobs/{delivery_id}/assign")
def assign_job(delivery_id: int, payload: DeliveryAssign, db: Session = Depends(get_db), user=Depends(require_staff)):
    return assign_delivery(db, restaurant_id_for(user), delivery_id, payload.agent_id)


@router.post("/jobs/{delivery_id}/status")
def job_status(delivery_id: int, payload: DeliveryStatusUpdate, db: Session = Depends(get_db), user=Depends(require_staff)):
    return update_status(db, restaurant_id_for(user), delivery_id, payload, "staff", str(getattr(user, "id", "")))


@router.post("/jobs/{delivery_id}/location")
def job_location(delivery_id: int, payload: DeliveryLocationUpdate, db: Session = Depends(get_db), user=Depends(require_staff)):
    return update_location(db, restaurant_id_for(user), delivery_id, payload)


@router.post("/jobs/{delivery_id}/refresh")
def refresh_job(delivery_id: int, db: Session = Depends(get_db), user=Depends(require_staff)):
    return refresh_external_status(db, restaurant_id_for(user), delivery_id)


@router.post("/jobs/{delivery_id}/cancel")
def cancel_job(delivery_id: int, db: Session = Depends(get_db), user=Depends(require_staff)):
    rid = restaurant_id_for(user)
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == rid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if job.status in {"delivered", "cancelled"}:
        return job
    if job.provider != "own_agent" and job.provider_delivery_id:
        try:
            provider_for(job.provider).cancel_delivery(job.provider_delivery_id)
        except ProviderNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ProviderRequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    job.status = "cancelled"
    db.add(DeliveryEvent(delivery_job_id=job.id, restaurant_id=rid, status="cancelled", actor_type="staff", actor_id=str(getattr(user, "id", "")), note="Cancelled from SpiceOS"))
    db.commit()
    db.refresh(job)
    return job


@router.get("/jobs/{delivery_id}/events")
def job_events(delivery_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rid = restaurant_id_for(user)
    job = db.query(DeliveryJob).filter(DeliveryJob.id == delivery_id, DeliveryJob.restaurant_id == rid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return db.query(DeliveryEvent).filter(DeliveryEvent.delivery_job_id == job.id).order_by(DeliveryEvent.id.asc()).all()


@router.get("/public/{delivery_token}")
def public_tracking(delivery_token: str, db: Session = Depends(get_db)):
    job = db.query(DeliveryJob).filter(DeliveryJob.delivery_token == delivery_token).first()
    if not job:
        raise HTTPException(status_code=404, detail="Tracking link not found")
    return {
        "delivery_token": job.delivery_token,
        "status": job.status,
        "provider": job.provider,
        "eta_minutes": job.eta_minutes,
        "tracking_url": job.tracking_url,
        "latitude": job.latitude,
        "longitude": job.longitude,
    }
