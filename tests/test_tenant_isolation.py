from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.inventory import adjust_inventory, get_inventory
from app.api.v1.orders import get_orders, update_order
from app.api.v1.users import UserRoleUpdate, list_users, update_user_role
from app.core.database import Base
from app.models.inventory_item import InventoryItem
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.inventory import InventoryAdjustment
from app.schemas.order import OrderUpdate


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed():
    db = make_db()
    db.add_all([
        Restaurant(restaurant_id="restaurant-a", name="Restaurant A", active=True),
        Restaurant(restaurant_id="restaurant-b", name="Restaurant B", active=True),
    ])
    owner_a = User(firebase_uid="uid-a", email="a@example.com", role="owner", restaurant_id="restaurant-a")
    owner_b = User(firebase_uid="uid-b", email="b@example.com", role="owner", restaurant_id="restaurant-b")
    staff_a = User(firebase_uid="uid-staff-a", email="staff-a@example.com", role="staff", restaurant_id="restaurant-a")
    db.add_all([owner_a, owner_b, staff_a])
    db.flush()
    order_a = Order(order_number="A-1", restaurant_id="restaurant-a", customer_name="A", total=10, created_at=datetime.utcnow(), status="created", payment_status="pending", order_source="manual")
    order_b = Order(order_number="B-1", restaurant_id="restaurant-b", customer_name="B", total=20, created_at=datetime.utcnow(), status="created", payment_status="pending", order_source="manual")
    db.add_all([order_a, order_b])
    db.add_all([
        InventoryItem(restaurant_id="restaurant-a", name="Rice A", unit="kg", quantity=10, reorder_level=2, cost_per_unit=50, is_active=True),
        InventoryItem(restaurant_id="restaurant-b", name="Rice B", unit="kg", quantity=10, reorder_level=2, cost_per_unit=50, is_active=True),
    ])
    db.commit()
    db.refresh(order_b)
    return db, owner_a, owner_b, staff_a, order_a, order_b


def test_orders_are_scoped_to_current_restaurant():
    db, _, _, staff_a, _, _ = seed()
    orders = get_orders(db=db, current_user=staff_a)
    assert [order.order_number for order in orders] == ["A-1"]


def test_cross_restaurant_order_cannot_be_updated():
    db, _, _, staff_a, _, order_b = seed()
    with pytest.raises(HTTPException) as exc:
        update_order(order_b.id, OrderUpdate(status="preparing"), db=db, current_user=staff_a)
    assert exc.value.status_code == 404


def test_owner_user_admin_is_scoped_to_current_restaurant():
    db, owner_a, _, _, _, _ = seed()
    users = list_users(db=db, current_user=owner_a)
    assert {user.email for user in users} == {"a@example.com", "staff-a@example.com"}


def test_owner_cannot_change_user_in_another_restaurant():
    db, owner_a, owner_b, _, _, _ = seed()
    with pytest.raises(HTTPException) as exc:
        update_user_role(owner_b.id, UserRoleUpdate(role="staff"), db=db, current_user=owner_a)
    assert exc.value.status_code == 404


def test_inventory_is_scoped_to_current_restaurant():
    db, _, _, staff_a, _, _ = seed()
    items = get_inventory(db=db, current_user=staff_a)
    assert [item.name for item in items] == ["Rice A"]


def test_cross_restaurant_inventory_cannot_be_adjusted():
    db, _, _, staff_a, _, _ = seed()
    other = db.query(InventoryItem).filter(InventoryItem.restaurant_id == "restaurant-b").one()
    with pytest.raises(HTTPException) as exc:
        adjust_inventory(other.id, InventoryAdjustment(quantity_delta=1, reason="test"), db=db, current_user=staff_a)
    assert exc.value.status_code == 404
