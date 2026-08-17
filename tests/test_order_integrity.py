import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.orders import create_order, update_order
from app.core.database import Base
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.order import OrderCreate, OrderUpdate


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed():
    db = make_db()
    db.add(Restaurant(restaurant_id="restaurant-a", name="Restaurant A", active=True))
    owner = User(firebase_uid="uid-owner", email="owner@example.com", role="owner", restaurant_id="restaurant-a")
    manager = User(firebase_uid="uid-manager", email="manager@example.com", role="manager", restaurant_id="restaurant-a")
    staff = User(firebase_uid="uid-staff", email="staff@example.com", role="staff", restaurant_id="restaurant-a")
    db.add_all([owner, manager, staff])
    db.commit()
    return db, owner, manager, staff


def create_manual(db, staff, payment_status="pending"):
    return create_order(
        OrderCreate(
            order_number="A-100",
            customer_name="Customer",
            primary_item="Paneer Butter Masala",
            total=249,
            payment_status=payment_status,
            order_source="manual",
        ),
        db=db,
        current_user=staff,
    )


def test_staff_cannot_mark_order_paid():
    db, _, _, staff = seed()
    create_manual(db, staff)
    with pytest.raises(HTTPException) as exc:
        update_order(1, OrderUpdate(payment_status="paid"), db=db, current_user=staff)
    assert exc.value.status_code == 403


def test_staff_cannot_change_order_total():
    db, _, _, staff = seed()
    create_manual(db, staff)
    with pytest.raises(HTTPException) as exc:
        update_order(1, OrderUpdate(total=1), db=db, current_user=staff)
    assert exc.value.status_code == 403


def test_manager_can_mark_pending_order_paid():
    db, _, manager, staff = seed()
    create_manual(db, staff)
    response = update_order(1, OrderUpdate(payment_status="paid"), db=db, current_user=manager)
    assert response.payment_status == "paid"


def test_refund_requires_paid_state():
    db, _, manager, staff = seed()
    create_manual(db, staff)
    with pytest.raises(HTTPException) as exc:
        update_order(1, OrderUpdate(payment_status="refunded"), db=db, current_user=manager)
    assert exc.value.status_code == 409


def test_manager_can_refund_paid_order():
    db, _, manager, staff = seed()
    create_manual(db, staff)
    update_order(1, OrderUpdate(payment_status="paid"), db=db, current_user=manager)
    response = update_order(1, OrderUpdate(payment_status="refunded"), db=db, current_user=manager)
    assert response.payment_status == "refunded"


def test_staff_cannot_create_order_as_paid():
    db, _, _, staff = seed()
    with pytest.raises(HTTPException) as exc:
        create_manual(db, staff, payment_status="paid")
    assert exc.value.status_code == 403


def test_qr_order_source_is_immutable():
    db, _, manager, staff = seed()
    order = Order(
        order_number="QR-100",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        total=249,
        status="created",
        payment_status="pending",
        order_source="qr_table",
    )
    db.add(order)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_order(order.id, OrderUpdate(order_source="manual"), db=db, current_user=manager)
    assert exc.value.status_code == 409


def test_qr_order_total_is_immutable():
    db, _, manager, staff = seed()
    order = Order(
        order_number="QR-101",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        total=249,
        status="created",
        payment_status="pending",
        order_source="qr_table",
    )
    db.add(order)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_order(order.id, OrderUpdate(total=1), db=db, current_user=manager)
    assert exc.value.status_code == 409
