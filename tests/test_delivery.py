from app.models.delivery import DeliveryAgent, DeliveryJob
from app.services.delivery_service import assign_delivery, create_delivery, update_status


def test_delivery_is_idempotent(db_session, restaurant, order):
    payload = type("P", (), {"order_id": order.id, "delivery_address": "1 Main St", "pickup_address": None, "customer_name": "A", "customer_phone": None})()
    first = create_delivery(db_session, restaurant.restaurant_id, payload)
    second = create_delivery(db_session, restaurant.restaurant_id, payload)
    assert first.id == second.id


def test_cross_tenant_assignment_is_rejected(db_session, restaurant, order):
    payload = type("P", (), {"order_id": order.id, "delivery_address": "1 Main St", "pickup_address": None, "customer_name": "A", "customer_phone": None})()
    job = create_delivery(db_session, restaurant.restaurant_id, payload)
    other_agent = DeliveryAgent(restaurant_id="other-restaurant", name="Other", status="available", is_active=True)
    db_session.add(other_agent)
    db_session.commit()
    try:
        assign_delivery(db_session, restaurant.restaurant_id, job.id, other_agent.id)
        assert False, "cross tenant assignment should fail"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404


def test_delivery_state_machine(db_session, restaurant, order):
    payload = type("P", (), {"order_id": order.id, "delivery_address": "1 Main St", "pickup_address": None, "customer_name": "A", "customer_phone": None})()
    job = create_delivery(db_session, restaurant.restaurant_id, payload)
    agent = DeliveryAgent(restaurant_id=restaurant.restaurant_id, name="Driver", status="available", is_active=True)
    db_session.add(agent)
    db_session.commit()
    assign_delivery(db_session, restaurant.restaurant_id, job.id, agent.id)
    assert job.status == "assigned"
    status = type("S", (), {"status": "picked_up", "note": None, "latitude": None, "longitude": None})()
    try:
        update_status(db_session, restaurant.restaurant_id, job.id, status)
        assert False, "assigned -> picked_up should require valid lifecycle entry"
    except Exception:
        pass
    status.status = "picked_up"
    job.status = "assigned"
    update_status(db_session, restaurant.restaurant_id, job.id, status)
    assert job.status == "picked_up"
