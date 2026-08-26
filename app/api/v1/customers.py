from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.order import Order
from app.models.user import User

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("")
def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    orders = (
        db.query(Order)
        .filter(Order.restaurant_id == current_user.restaurant_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .all()
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "customer_id": None,
            "name": "Guest",
            "phone": None,
            "orders": 0,
            "paid_sales": 0.0,
            "last_order_at": None,
            "sources": set(),
        }
    )
    for order in orders:
        key = order.customer_id or (order.customer_phone or order.customer_name or f"guest:{order.id}")
        customer = grouped[key]
        customer["customer_id"] = order.customer_id or key
        customer["name"] = order.customer_name or "Guest"
        customer["phone"] = order.customer_phone
        customer["orders"] += 1
        if order.payment_status == "paid" and order.status != "cancelled":
            customer["paid_sales"] += float(order.total or 0)
        if customer["last_order_at"] is None and order.created_at:
            customer["last_order_at"] = order.created_at.isoformat()
        if order.order_source:
            customer["sources"].add(order.order_source)

    result = []
    for customer in grouped.values():
        customer["paid_sales"] = round(customer["paid_sales"], 2)
        customer["sources"] = sorted(customer["sources"])
        result.append(customer)
    result.sort(key=lambda item: (item["paid_sales"], item["orders"]), reverse=True)
    return result
