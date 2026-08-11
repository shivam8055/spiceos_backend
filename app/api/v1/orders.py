from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.order import Order
from app.models.user import User

router = APIRouter()


class OrderCreate(BaseModel):
    order_number: str
    customer_name: str
    total: float


@router.get("/")
def get_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    orders = db.query(Order).all()

    return [
        {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "total": order.total,
        }
        for order in orders
    ]


@router.post("/")
def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
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
