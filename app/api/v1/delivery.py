from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user
from app.models.delivery import DeliveryAgent, DeliveryEvent, DeliveryJob
from app.schemas.delivery import DeliveryAgentCreate, DeliveryAgentUpdate, DeliveryAssign, DeliveryCreate, DeliveryLocationUpdate, DeliveryStatusUpdate
from app.services.delivery_service import create_delivery, assign_delivery, update_location, update_status

router = APIRouter(prefix="/delivery", tags=["delivery"])


def restaurant_id_for(user):
    restaurant_id = getattr(user, "restaurant_id", None)
    if not restaurant_id:
        raise HTTPException(status_code=403, detail="Restaurant is not assigned")
    return restaurant_id


@router.get("/agents")
def list_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rid = restaurant_id_for(user)
    return db.query(DeliveryAgent).filter(DeliveryAgent.restaurant_id == rid).order_by(DeliveryAgent.id.desc()).all()


@router.post("/agents", status_code=201)
def create_agent(payload: DeliveryAgentCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rid = restaurant_id_for(user)
    agent = DeliveryAgent(restaurant_id=rid, name=payload.name, phone=payload.phone, status="offline")
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: int, payload: DeliveryAgentUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
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
def create_job(payload: DeliveryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return create_delivery(db, restaurant_id_for(user), payload)


@router.post("/jobs/{delivery_id}/assign")
def assign_job(delivery_id: int, payload: DeliveryAssign, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return assign_delivery(db, restaurant_id_for(user), delivery_id, payload.agent_id)


@router.post("/jobs/{delivery_id}/status")
def job_status(delivery_id: int, payload: DeliveryStatusUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return update_status(db, restaurant_id_for(user), delivery_id, payload, "staff", str(getattr(user, "id", "")))


@router.post("/jobs/{delivery_id}/location")
def job_location(delivery_id: int, payload: DeliveryLocationUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return update_location(db, restaurant_id_for(user), delivery_id, payload)


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
    return {"delivery_token": job.delivery_token, "status": job.status, "provider": job.provider, "eta_minutes": job.eta_minutes, "latitude": job.latitude, "longitude": job.longitude}
