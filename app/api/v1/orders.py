from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.order import Order
from app.models.user import User
from app.schemas.order import OrderCreate, OrderResponse, OrderUpdate

router = APIRouter()

VALID_STATUSES = {"created", "preparing", "ready", "outForDelivery", "delivered", "cancelled"}
VALID_PAYMENT_STATUSES = {"paid", "pending", "refunded"}


def _ensure_order_defaults(order: Order) -> None:
    if order.created_at is None:
        order.created_at = datetime.utcnow()
    if not order.status:
        order.status = "created"
    if not order.payment_status:
        order.payment_status = "pending"
    if not order.order_source:
        order.order_source = "Unknown"


def _serialize_order(order: Order) -> OrderResponse:
    _ensure_order_defaults(order)
    return OrderResponse.model_validate(order)


@router.get("/", response_model=list[OrderResponse])
def get_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    orders = db.query(Order).order_by(Order.created_at.desc(), Order.id.desc()).all()
    changed = False
    for order in orders:
        before = (order.created_at, order.status, order.payment_status, order.order_source)
        _ensure_order_defaults(order)
        changed = changed or before != (order.created_at, order.status, order.payment_status, order.order_source)
    if changed:
        db.commit()
    return [_serialize_order(order) for order in orders]


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    if db.query(Order).filter(Order.order_number == order.order_number).first():
        raise HTTPException(status_code=409, detail="Order number already exists.")
    if order.payment_status not in VALID_PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid payment status.")

    new_order = Order(
        order_number=order.order_number,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        primary_item=order.primary_item,
        total=order.total,
        status="created",
        payment_status=order.payment_status,
        order_source=order.order_source,
        created_at=datetime.utcnow(),
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return _serialize_order(new_order)


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    order_update: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")

    updates = order_update.model_dump(exclude_unset=True)
    if "status" in updates:
        if updates["status"] not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid order status.")
        order.status = updates.pop("status")
    if "payment_status" in updates:
        if updates["payment_status"] not in VALID_PAYMENT_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid payment status.")

    for field, value in updates.items():
        setattr(order, field, value)

    _ensure_order_defaults(order)
    db.commit()
    db.refresh(order)
    return _serialize_order(order)
