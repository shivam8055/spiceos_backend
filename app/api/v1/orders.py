from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_manager, require_staff
from app.core.database import get_db
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.order import OrderCreate, OrderResponse, OrderUpdate

router = APIRouter()

VALID_STATUSES = {"created", "preparing", "ready", "outForDelivery", "delivered", "cancelled"}
VALID_PAYMENT_STATUSES = {"paid", "pending", "refunded"}
INITIAL_PAYMENT_STATUSES = {"paid", "pending"}
PAYMENT_TRANSITIONS = {
    "pending": {"paid"},
    "paid": {"refunded"},
    "refunded": set(),
}
STATUS_TRANSITIONS = {
    "created": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"outForDelivery", "cancelled"},
    "outForDelivery": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


def _require_restaurant(current_user: User, db: Session) -> Restaurant:
    if not current_user.restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not associated with a restaurant.",
        )
    restaurant = (
        db.query(Restaurant)
        .filter(
            Restaurant.restaurant_id == current_user.restaurant_id,
            Restaurant.active.is_(True),
        )
        .first()
    )
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restaurant access is inactive or invalid.",
        )
    return restaurant


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
    restaurant = _require_restaurant(current_user, db)
    orders = (
        db.query(Order)
        .filter(Order.restaurant_id == restaurant.restaurant_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .all()
    )
    changed = False
    for order in orders:
        before = (
            order.created_at,
            order.status,
            order.payment_status,
            order.order_source,
        )
        _ensure_order_defaults(order)
        changed = changed or before != (
            order.created_at,
            order.status,
            order.payment_status,
            order.order_source,
        )
    if changed:
        db.commit()
    return [_serialize_order(order) for order in orders]


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant = _require_restaurant(current_user, db)
    if db.query(Order).filter(Order.order_number == order.order_number).first():
        raise HTTPException(status_code=409, detail="Order number already exists.")
    if order.payment_status not in INITIAL_PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail="New orders may only be pending or paid.")
    if order.payment_status == "paid" and current_user.role not in {"manager", "owner"}:
        raise HTTPException(status_code=403, detail="Only a manager or owner can mark a new order as paid.")

    new_order = Order(
        order_number=order.order_number,
        restaurant_id=restaurant.restaurant_id,
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
    restaurant = _require_restaurant(current_user, db)
    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.restaurant_id == restaurant.restaurant_id,
        )
        .first()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")

    updates = order_update.model_dump(exclude_unset=True)

    if "status" in updates:
        next_status = updates.pop("status")
        if next_status not in VALID_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid order status.")
        current_status = order.status or "created"
        allowed_next = STATUS_TRANSITIONS.get(current_status, set())
        if next_status != current_status and next_status not in allowed_next:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid order status transition: {current_status} -> {next_status}.",
            )
        if (
            current_status == "created"
            and next_status == "preparing"
            and order.order_source == "qr_table"
            and (order.payment_status or "pending") != "paid"
        ):
            raise HTTPException(
                status_code=409,
                detail="QR orders must be paid before kitchen preparation can start.",
            )
        order.status = next_status

    if "payment_status" in updates:
        next_payment_status = updates.pop("payment_status")
        if next_payment_status not in VALID_PAYMENT_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid payment status.")
        current_payment_status = order.payment_status or "pending"
        if next_payment_status != current_payment_status:
            if current_user.role not in {"manager", "owner"}:
                raise HTTPException(status_code=403, detail="Only a manager or owner can change payment status.")
            allowed_next = PAYMENT_TRANSITIONS.get(current_payment_status, set())
            if next_payment_status not in allowed_next:
                raise HTTPException(
                    status_code=409,
                    detail=f"Invalid payment status transition: {current_payment_status} -> {next_payment_status}.",
                )
        order.payment_status = next_payment_status

    if "total" in updates:
        next_total = updates.pop("total")
        if next_total != order.total:
            if order.order_source == "qr_table":
                raise HTTPException(status_code=409, detail="QR order totals are server-authoritative and cannot be changed.")
            if current_user.role not in {"manager", "owner"}:
                raise HTTPException(status_code=403, detail="Only a manager or owner can change order totals.")
        order.total = next_total

    if "order_source" in updates:
        next_source = updates.pop("order_source")
        if next_source != order.order_source:
            raise HTTPException(status_code=409, detail="Order source is immutable.")

    for field, value in updates.items():
        setattr(order, field, value)

    _ensure_order_defaults(order)
    db.commit()
    db.refresh(order)
    return _serialize_order(order)