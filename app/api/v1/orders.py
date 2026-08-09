from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.order import Order

router = APIRouter()


class OrderCreate(BaseModel):
    order_number: str
    customer_name: str
    total: float


@router.get("/")
def get_orders():
    db: Session = SessionLocal()
    try:
        orders = db.query(Order).all()
        return [
            {
                "id": o.id,
                "order_number": o.order_number,
                "customer_name": o.customer_name,
                "total": o.total,
            }
            for o in orders
        ]
    finally:
        db.close()


@router.post("/")
def create_order(order: OrderCreate):
    db: Session = SessionLocal()

    try:
        new_order = Order(
            order_number=order.order_number,
            customer_name=order.customer_name,
            total=order.total,
        )

        db.add(new_order)
        db.commit()
        db.refresh(new_order)

        return {
            "id": new_order.id,
            "message": "Order created successfully",
        }
    finally:
        db.close()