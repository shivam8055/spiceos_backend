import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.qr_ordering import _require_restaurant, _validate_tenant_payload, create_restaurant, update_menu_item
from app.core.database import Base
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.qr_admin import MenuItemUpdateRequest, RestaurantCreateRequest


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_user_can_resolve_only_active_restaurant():
    db = make_db()
    db.add(Restaurant(restaurant_id="spice-box", name="Spice Box", active=True))
    user = User(firebase_uid="uid-1", email="owner@example.com", role="owner", restaurant_id="spice-box")
    db.add(user)
    db.commit()
    assert _require_restaurant(user, db).restaurant_id == "spice-box"


def test_unassigned_user_cannot_manage_menu_or_qr():
    db = make_db()
    user = User(firebase_uid="uid-2", email="new@example.com", role="owner", restaurant_id=None)
    db.add(user)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _require_restaurant(user, db)
    assert exc.value.status_code == 409


def test_cross_restaurant_resource_is_rejected():
    db = make_db()
    restaurant = Restaurant(restaurant_id="spice-box", name="Spice Box", active=True)
    db.add(restaurant)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _validate_tenant_payload("other-restaurant", restaurant)
    assert exc.value.status_code == 403


def test_create_restaurant_persists_user_association_from_detached_user():
    db = make_db()
    user = User(firebase_uid="uid-3", email="new-owner@example.com", role="owner", restaurant_id=None)
    db.add(user)
    db.commit()
    db.expunge(user)
    create_restaurant(RestaurantCreateRequest(name="Spice Box"), db, user)
    refreshed = db.query(User).filter(User.firebase_uid == "uid-3").one()
    assert refreshed.restaurant_id is not None
    assert db.query(Restaurant).filter(Restaurant.restaurant_id == refreshed.restaurant_id).one().name == "Spice Box"


def test_owner_can_update_own_menu_item_and_toggle_availability():
    db = make_db()
    restaurant = Restaurant(restaurant_id="spice-box", name="Spice Box", active=True)
    user = User(firebase_uid="uid-menu", email="menu@example.com", role="owner", restaurant_id="spice-box")
    item = MenuItem(restaurant_id="spice-box", branch_id="main", category="Mains", name="Paneer Tikka", description="Smoky paneer", price=249, available=True, modifiers_json="[]")
    db.add_all([restaurant, user, item])
    db.commit()
    db.refresh(item)
    updated = update_menu_item(item.id, MenuItemUpdateRequest(price=279, available=False, description="Smoky paneer with mint chutney"), db, user)
    assert updated.id == item.id
    assert updated.price == 279
    assert updated.available is False
    assert updated.description == "Smoky paneer with mint chutney"


def test_menu_update_cannot_cross_tenant_boundary():
    db = make_db()
    db.add_all([
        Restaurant(restaurant_id="spice-box", name="Spice Box", active=True),
        Restaurant(restaurant_id="other", name="Other Kitchen", active=True),
    ])
    user = User(firebase_uid="uid-menu-2", email="menu2@example.com", role="owner", restaurant_id="spice-box")
    item = MenuItem(restaurant_id="other", branch_id="main", category="Mains", name="Secret Dish", price=999, available=True, modifiers_json="[]")
    db.add_all([user, item])
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_menu_item(item.id, MenuItemUpdateRequest(available=False), db, user)
    assert exc.value.status_code == 404
