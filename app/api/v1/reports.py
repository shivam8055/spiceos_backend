from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_manager
from app.core.database import get_db
from app.models.order import Order
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["reports"])


def _parse_date(value: str | None, *, default: datetime) -> datetime:
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d")


@router.get("/summary")
def reports_summary(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager),
):
    end = _parse_date(end_date, default=datetime.utcnow()).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    start = _parse_date(start_date, default=(end - timedelta(days=29))).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), start.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    orders = (
        db.query(Order)
        .filter(
            Order.restaurant_id == current_user.restaurant_id,
            Order.created_at >= start,
            Order.created_at <= end,
        )
        .order_by(Order.created_at.asc(), Order.id.asc())
        .all()
    )

    total_orders = len(orders)
    completed_orders = sum(1 for order in orders if (order.status or "created") == "delivered")
    cancelled_orders = sum(1 for order in orders if (order.status or "created") == "cancelled")
    paid_orders = [order for order in orders if (order.payment_status or "pending") == "paid"]
    refunded_orders = [order for order in orders if (order.payment_status or "pending") == "refunded"]
    paid_sales = sum(float(order.total or 0) for order in paid_orders if order.status != "cancelled")
    refunded_sales = sum(float(order.total or 0) for order in refunded_orders)
    net_sales = max(0.0, paid_sales - refunded_sales)
    pending_amount = sum(
        float(order.total or 0)
        for order in orders
        if (order.payment_status or "pending") == "pending" and order.status != "cancelled"
    )

    source_totals: dict[str, dict[str, float | int]] = {}
    daily: dict[str, dict[str, float | int]] = {}
    for order in orders:
        source = (order.order_source or "Unknown").strip() or "Unknown"
        source_entry = source_totals.setdefault(source, {"orders": 0, "sales": 0.0})
        source_entry["orders"] += 1
        if order.payment_status == "paid" and order.status != "cancelled":
            source_entry["sales"] += float(order.total or 0)

        day = (order.created_at or start).date().isoformat()
        day_entry = daily.setdefault(day, {"orders": 0, "sales": 0.0})
        day_entry["orders"] += 1
        if order.payment_status == "paid" and order.status != "cancelled":
            day_entry["sales"] += float(order.total or 0)

    average_order_value = net_sales / len(paid_orders) if paid_orders else 0.0
    completion_rate = (completed_orders / total_orders * 100) if total_orders else 0.0
    cancellation_rate = (cancelled_orders / total_orders * 100) if total_orders else 0.0

    return {
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "kpis": {
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "paid_sales": round(paid_sales, 2),
            "refunded_sales": round(refunded_sales, 2),
            "net_sales": round(net_sales, 2),
            "pending_amount": round(pending_amount, 2),
            "average_order_value": round(average_order_value, 2),
            "completion_rate": round(completion_rate, 2),
            "cancellation_rate": round(cancellation_rate, 2),
        },
        "by_source": [
            {"source": source, **values}
            for source, values in sorted(
                source_totals.items(), key=lambda item: float(item[1]["sales"]), reverse=True
            )
        ],
        "daily": [
            {"date": day, **values}
            for day, values in sorted(daily.items())
        ],
    }
