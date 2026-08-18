from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.qr_table import QRTable
from app.schemas.qr_ordering import QROrderCreateRequest, QROrderItemRequest
from app.services.qr_ordering import create_qr_order, get_public_order_status, hash_token, menu_response, resolve_qr_table


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed_table(db):
    table = QRTable(
        restaurant_id="restaurant-1",
        branch_id="branch-1",
        table_id="table-1",
        table_name="Table 1",
        session_id="session-1",
        token_hash=hash_token("valid-qr-token-1234567890"),
        active=True,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(table)
    db.add(MenuItem(
        restaurant_id="restaurant-1",
        branch_id="branch-1",
        category="Mains",
        name="Paneer Tikka",
        description="Test item",
        price=250,
        available=True,
        modifiers_json='[{"id":"extra-cheese","name":"Extra Cheese","price_delta":40,"available":true}]',
    ))
    db.commit()
    db.refresh(table)
    return table


def test_invalid_qr_token_is_rejected():
    db = make_db()
    seed_table(db)
    try:
        resolve_qr_table(db, "invalid-token-1234567890")
        assert False, "invalid QR token must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_server_calculates_price_and_ignores_client_price():
    db = make_db()
    table = seed_table(db)
    payload = QROrderCreateRequest(items=[QROrderItemRequest(menu_item_id=1, quantity=2, modifier_ids=["extra-cheese"])])
    response = create_qr_order(db, table, payload, "idempotency-1")
    assert response.total == 580
    order = db.query(Order).filter(Order.id == response.order_id).one()
    assert order.order_source == "qr_table"
    assert db.query(OrderItem).filter(OrderItem.order_id == order.id).one().unit_price == 290


def test_duplicate_submit_returns_same_order():
    db = make_db()
    table = seed_table(db)
    payload = QROrderCreateRequest(items=[QROrderItemRequest(menu_item_id=1, quantity=1)])
    first = create_qr_order(db, table, payload, "same-key")
    second = create_qr_order(db, table, payload, "same-key")
    assert second.order_id == first.order_id
    assert second.order_number == first.order_number
    assert second.public_order_token == first.public_order_token
    assert db.query(Order).count() == 1


def test_unavailable_item_is_rejected():
    db = make_db()
    table = seed_table(db)
    item = db.query(MenuItem).one()
    item.available = False
    db.commit()
    payload = QROrderCreateRequest(items=[QROrderItemRequest(menu_item_id=item.id, quantity=1)])
    try:
        create_qr_order(db, table, payload, "unavailable-key")
        assert False, "unavailable item must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 409


def test_public_status_is_customer_safe():
    db = make_db()
    table = seed_table(db)
    payload = QROrderCreateRequest(items=[QROrderItemRequest(menu_item_id=1, quantity=1)])
    created = create_qr_order(db, table, payload, "status-key")
    status_response = get_public_order_status(db, created.public_order_token)
    assert status_response.order_number == created.order_number
    assert status_response.status == "created"
    assert status_response.total == 250


def test_expired_qr_is_rejected():
    db = make_db()
    seed_table(db)
    table = db.query(QRTable).one()
    table.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    try:
        resolve_qr_table(db, "valid-qr-token-1234567890")
        assert False, "expired QR must be rejected"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_qr_menu_ignores_malformed_modifier_entries():
    db = make_db()
    table = seed_table(db)
    item = db.query(MenuItem).filter(MenuItem.id == 1).one()
    item.modifiers_json = '[null, "legacy", 123, {"id":"valid","name":"Valid","price_delta":10}]'
    db.commit()

    response = menu_response(db, table)

    assert len(response.items) == 1
    assert len(response.items[0].modifiers) == 1
    assert response.items[0].modifiers[0].id == "valid"


def test_qr_menu_and_order_cannot_cross_restaurant_boundaries():
    db = make_db()
    table_a = QRTable(
        restaurant_id="restaurant-a",
        branch_id="branch-1",
        table_id="table-a",
        table_name="A1",
        session_id="session-a",
        token_hash=hash_token("restaurant-a-token-1234567890"),
        active=True,
    )
    table_b = QRTable(
        restaurant_id="restaurant-b",
        branch_id="branch-1",
        table_id="table-b",
        table_name="B1",
        session_id="session-b",
        token_hash=hash_token("restaurant-b-token-1234567890"),
        active=True,
    )
    db.add_all([table_a, table_b])
    db.add_all([
        MenuItem(restaurant_id="restaurant-a", branch_id="branch-1", category="Mains", name="A Dish", price=100, available=True, modifiers_json="[]"),
        MenuItem(restaurant_id="restaurant-b", branch_id="branch-1", category="Mains", name="B Dish", price=200, available=True, modifiers_json="[]"),
    ])
    db.commit()
    db.refresh(table_a)
    db.refresh(table_b)

    menu_a = menu_response(db, table_a)
    assert [item.name for item in menu_a.items] == ["A Dish"]

    payload = QROrderCreateRequest(items=[QROrderItemRequest(menu_item_id=2, quantity=1)])
    with pytest.raises(HTTPException) as exc:
        create_qr_order(db, table_a, payload, "cross-tenant-key")
    assert exc.value.status_code == 422
