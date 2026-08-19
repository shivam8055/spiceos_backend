import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.delivery import DeliveryAgent
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.delivery_service import assign_delivery, create_delivery, update_status


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed():
    db = make_db()
    restaurant = Restaurant(restaurant_id="restaurant-a", name="Restaurant A", active=True)
    order = Order(order_number="DEL-1", restaurant_id="restaurant-a", customer_name="A", total=500, status="ready", payment_status="paid", order_source="manual")
    db.add_all([restaurant, order])
    db.commit()
    db.refresh(order)
    return db, restaurant, order


def payload(order_id, provider="own_agent"):
    return type(
        "P",
        (),
        {
            "order_id": order_id,
            "delivery_address": "1 Main St",
            "pickup_address": "2 Store St",
            "customer_name": "A",
            "customer_phone": "+919999999999",
            "provider": provider,
        },
    )()


def test_delivery_is_idempotent():
    db, restaurant, order = seed()
    first = create_delivery(db, restaurant.restaurant_id, payload(order.id))
    second = create_delivery(db, restaurant.restaurant_id, payload(order.id))
    assert first.id == second.id


def test_cross_tenant_assignment_is_rejected():
    db, restaurant, order = seed()
    job = create_delivery(db, restaurant.restaurant_id, payload(order.id))
    other_agent = DeliveryAgent(restaurant_id="other-restaurant", name="Other", status="available", is_active=True)
    db.add(other_agent)
    db.commit()
    with pytest.raises(Exception) as exc:
        assign_delivery(db, restaurant.restaurant_id, job.id, other_agent.id)
    assert getattr(exc.value, "status_code", None) == 404


def test_delivery_state_machine():
    db, restaurant, order = seed()
    job = create_delivery(db, restaurant.restaurant_id, payload(order.id))
    agent = DeliveryAgent(restaurant_id=restaurant.restaurant_id, name="Driver", status="available", is_active=True)
    db.add(agent)
    db.commit()
    assign_delivery(db, restaurant.restaurant_id, job.id, agent.id)
    assert job.status == "assigned"

    status = type("S", (), {"status": "picked_up", "note": None, "latitude": None, "longitude": None})()
    update_status(db, restaurant.restaurant_id, job.id, status)
    assert job.status == "picked_up"

    status.status = "out_for_delivery"
    update_status(db, restaurant.restaurant_id, job.id, status)
    assert job.status == "out_for_delivery"

    status.status = "delivered"
    update_status(db, restaurant.restaurant_id, job.id, status)
    assert job.status == "delivered"
    assert agent.status == "available"
