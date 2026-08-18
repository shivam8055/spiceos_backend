import base64
import hashlib
import hmac
import json
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import PUBLIC_QR_BASE_URL, QR_PUBLIC_TOKEN_SECRET
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.qr_table import QRTable
from app.schemas.qr_ordering import (
    QROrderCreateRequest,
    QROrderCreateResponse,
    QROrderStatusResponse,
    QRContextResponse,
    QRMenuItemResponse,
    QRMenuResponse,
    QRModifierResponse,
)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_order_token(table: QRTable, idempotency_key: str) -> str:
    message = f"{table.id}:{table.token_hash}:{idempotency_key}".encode("utf-8")
    digest = hmac.new(QR_PUBLIC_TOKEN_SECRET.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def resolve_qr_table(db: Session, token: str) -> QRTable:
    if not token or len(token) < 20:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code is invalid or expired.")
    table = db.query(QRTable).filter(QRTable.token_hash == hash_token(token)).first()
    now = datetime.utcnow()
    if table is None or not table.active or (table.expires_at is not None and table.expires_at <= now):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QR code is invalid or expired.")
    return table


def _safe_modifier_price(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_modifiers(item: MenuItem) -> list[dict]:
    """Return only safe modifier objects from persisted menu data.

    Menu data can be imported or edited outside the QR flow. Malformed
    modifier entries must never take down the public menu endpoint.
    """
    try:
        modifiers = json.loads(item.modifiers_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(modifiers, list):
        return []

    safe_modifiers = []
    for modifier in modifiers:
        if not isinstance(modifier, dict) or modifier.get("id") is None:
            continue
        safe_modifiers.append(
            {
                "id": str(modifier["id"]),
                "name": str(modifier.get("name", "")),
                "price_delta": _safe_modifier_price(modifier.get("price_delta", 0)),
                "available": bool(modifier.get("available", True)),
            }
        )
    return safe_modifiers


def menu_response(db: Session, table: QRTable) -> QRMenuResponse:
    items = (
        db.query(MenuItem)
        .filter(MenuItem.restaurant_id == table.restaurant_id, MenuItem.branch_id == table.branch_id)
        .order_by(MenuItem.category.asc(), MenuItem.name.asc())
        .all()
    )
    response_items = []
    for item in items:
        modifiers = [
            QRModifierResponse(
                id=modifier["id"],
                name=modifier["name"],
                price_delta=modifier["price_delta"],
                available=modifier["available"],
            )
            for modifier in parse_modifiers(item)
        ]
        response_items.append(
            QRMenuItemResponse(
                id=item.id,
                category=item.category,
                name=item.name,
                description=item.description,
                price=float(item.price),
                available=bool(item.available),
                modifiers=modifiers,
            )
        )
    return QRMenuResponse(
        context=QRContextResponse(
            restaurant_id=table.restaurant_id,
            branch_id=table.branch_id,
            table_id=table.table_id,
            table_name=table.table_name,
            session_id=table.session_id,
        ),
        categories=list(dict.fromkeys(item.category for item in response_items)),
        items=response_items,
    )


def create_qr_order(db: Session, table: QRTable, payload: QROrderCreateRequest, idempotency_key: str) -> QROrderCreateResponse:
    key = idempotency_key.strip()
    if not key or len(key) > 255:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid Idempotency-Key is required.")

    existing = db.query(Order).filter(Order.idempotency_key == key).first()
    if existing is not None:
        if existing.qr_table_id != table.id or existing.restaurant_id != table.restaurant_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was already used for another table.")
        return QROrderCreateResponse(
            order_id=existing.id,
            order_number=existing.order_number,
            status=existing.status or "created",
            total=float(existing.total),
            currency="INR",
            table_name=table.table_name,
            public_order_token=public_order_token(table, key),
        )

    menu_ids = {line.menu_item_id for line in payload.items}
    menu_items = (
        db.query(MenuItem)
        .filter(
            MenuItem.id.in_(menu_ids),
            MenuItem.restaurant_id == table.restaurant_id,
            MenuItem.branch_id == table.branch_id,
        )
        .all()
    )
    by_id = {item.id: item for item in menu_items}
    if len(by_id) != len(menu_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more menu items are unavailable.")

    calculated_total = 0.0
    snapshots: list[dict] = []
    for line in payload.items:
        item = by_id[line.menu_item_id]
        if not item.available:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{item.name} is currently unavailable.")
        modifiers_by_id = {str(m.get("id")): m for m in parse_modifiers(item)}
        selected_modifiers = []
        modifier_delta = 0.0
        for modifier_id in line.modifier_ids:
            modifier = modifiers_by_id.get(str(modifier_id))
            if modifier is None or not bool(modifier.get("available", True)):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A selected modifier for {item.name} is unavailable.")
            delta = _safe_modifier_price(modifier.get("price_delta", 0))
            modifier_delta += delta
            selected_modifiers.append({"id": str(modifier_id), "name": str(modifier.get("name", "")), "price_delta": delta})
        unit_price = float(item.price) + modifier_delta
        line_total = unit_price * line.quantity
        calculated_total += line_total
        snapshots.append({"item": item, "quantity": line.quantity, "unit_price": unit_price, "line_total": line_total, "modifiers": selected_modifiers, "note": line.note})

    public_token = public_order_token(table, key)
    order = Order(
        order_number=f"QR-{uuid4().hex[:12].upper()}",
        restaurant_id=table.restaurant_id,
        customer_id=None,
        customer_name=(payload.customer_name or "QR Guest").strip() or "QR Guest",
        customer_phone=payload.customer_phone or None,
        primary_item=snapshots[0]["item"].name,
        total=round(calculated_total, 2),
        status="created",
        payment_status="pending",
        order_source="qr_table",
        qr_table_id=table.id,
        qr_session_id=table.session_id,
        idempotency_key=key,
        public_token_hash=hash_token(public_token),
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()
    for snapshot in snapshots:
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=snapshot["item"].id,
                item_name=snapshot["item"].name,
                quantity=snapshot["quantity"],
                unit_price=snapshot["unit_price"],
                modifiers_json=json.dumps(snapshot["modifiers"], separators=(",", ":")),
                line_total=snapshot["line_total"],
                note=snapshot["note"],
            )
        )
    db.commit()
    db.refresh(order)
    return QROrderCreateResponse(
        order_id=order.id,
        order_number=order.order_number,
        status=order.status or "created",
        total=float(order.total),
        currency="INR",
        table_name=table.table_name,
        public_order_token=public_token,
    )


def get_public_order_status(db: Session, public_token: str) -> QROrderStatusResponse:
    order = db.query(Order).filter(Order.public_token_hash == hash_token(public_token)).first()
    if order is None or order.order_source != "qr_table" or order.qr_table_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order status not found.")
    table = db.query(QRTable).filter(QRTable.id == order.qr_table_id).first()
    if table is None or order.restaurant_id != table.restaurant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order status not found.")
    return QROrderStatusResponse(
        order_number=order.order_number,
        status=order.status or "created",
        payment_status=order.payment_status or "pending",
        total=float(order.total),
        currency="INR",
        table_name=table.table_name,
        created_at=(order.created_at or datetime.utcnow()).isoformat(),
    )


def qr_url(token: str) -> str:
    base = PUBLIC_QR_BASE_URL.rstrip('/')
    if '#/' in base:
        return f'{base}/{token}'
    if base.endswith('/order'):
        return f'{base[:-6]}/#/order/{token}'
    return f'{base}/#/{token}'
