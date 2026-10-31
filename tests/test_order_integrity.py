import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.orders import create_order, get_orders, update_order
from app.core.database import Base
from app.models.order import Order
from app.models.order_item import OrderItem
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


def create_manual(db, user, payment_status="pending", order_number="A-100"):
    return create_order(
        OrderCreate(
            order_number=order_number,
            customer_name="Customer",
            primary_item="Paneer Butter Masala",
            total=249,
            payment_status=payment_status,
            order_source="manual",
        ),
        db=db,
        current_user=user,
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


def test_new_order_cannot_start_refunded():
    db, _, manager, _ = seed()
    with pytest.raises(HTTPException) as exc:
        create_manual(db, manager, payment_status="refunded", order_number="A-101")
    assert exc.value.status_code == 422


def test_qr_order_source_is_immutable():
    db, _, manager, _ = seed()
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
    db, _, manager, _ = seed()
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


def test_qr_order_cannot_start_preparation_before_payment():
    db, _, manager, _ = seed()
    order = Order(
        order_number="QR-102",
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
        update_order(order.id, OrderUpdate(status="preparing"), db=db, current_user=manager)

    assert exc.value.status_code == 409
    assert "must be paid" in exc.value.detail


def test_paid_qr_order_can_start_preparation_and_records_server_time():
    db, _, manager, _ = seed()
    order = Order(
        order_number="QR-103",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        total=249,
        status="created",
        payment_status="paid",
        order_source="qr_table",
    )
    db.add(order)
    db.commit()

    assert order.preparing_at is None
    response = update_order(order.id, OrderUpdate(status="preparing"), db=db, current_user=manager)

    assert response.status == "preparing"
    assert response.preparing_at is not None
    assert response.preparing_at >= order.created_at


def test_preparation_start_time_is_not_reset_by_later_status_updates():
    db, _, manager, _ = seed()
    order = Order(
        order_number="QR-104",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        total=249,
        status="created",
        payment_status="paid",
        order_source="qr_table",
    )
    db.add(order)
    db.commit()

    started = update_order(order.id, OrderUpdate(status="preparing"), db=db, current_user=manager)
    preparing_at = started.preparing_at

    ready = update_order(order.id, OrderUpdate(status="ready"), db=db, current_user=manager)

    assert ready.status == "ready"
    assert ready.preparing_at == preparing_at
    assert ready.ready_at is not None


def test_full_status_timeline_records_each_transition_once():
    db, _, manager, _ = seed()
    order = Order(
        order_number="QR-105",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        total=249,
        status="created",
        payment_status="paid",
        order_source="qr_table",
    )
    db.add(order)
    db.commit()

    preparing = update_order(order.id, OrderUpdate(status="preparing"), db=db, current_user=manager)
    preparing_at = preparing.preparing_at
    ready = update_order(order.id, OrderUpdate(status="ready"), db=db, current_user=manager)
    ready_at = ready.ready_at
    out = update_order(order.id, OrderUpdate(status="outForDelivery"), db=db, current_user=manager)
    out_at = out.out_for_delivery_at
    delivered = update_order(order.id, OrderUpdate(status="delivered"), db=db, current_user=manager)

    assert delivered.preparing_at == preparing_at
    assert delivered.ready_at == ready_at
    assert delivered.out_for_delivery_at == out_at
    assert delivered.delivered_at is not None
    assert delivered.preparing_at <= delivered.ready_at <= delivered.out_for_delivery_at <= delivered.delivered_at



def test_order_response_includes_all_line_items_and_quantities():
    db, _, _, staff = seed()
    order = Order(
        order_number="QR-ITEMS-1",
        restaurant_id="restaurant-a",
        customer_name="QR Guest",
        primary_item="Chocolate Shake",
        total=654,
        status="preparing",
        payment_status="paid",
        order_source="qr_table",
    )
    db.add(order)
    db.flush()
    db.add_all(
        [
            OrderItem(
                order_id=order.id,
                menu_item_id=101,
                item_name="Chocolate Shake",
                quantity=2,
                unit_price=327,
                modifiers_json="[]",
                line_total=654,
            ),
            OrderItem(
                order_id=order.id,
                menu_item_id=102,
                item_name="Paneer Tikka",
                quantity=1,
                unit_price=199,
                modifiers_json="[]",
                line_total=199,
            ),
        ]
    )
    db.commit()

    responses = get_orders(db=db, current_user=staff)
    response = next(item for item in responses if item.order_number == "QR-ITEMS-1")

    assert [(item.item_name, item.quantity, item.line_total) for item in response.items] == [
        ("Chocolate Shake", 2, 654),
        ("Paneer Tikka", 1, 199),
    ]
