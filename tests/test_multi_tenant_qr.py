import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.qr_ordering import _require_restaurant, _validate_tenant_payload
from app.core.database import Base
from app.models.restaurant import Restaurant
from app.models.user import User


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_user_can_resolve_only_active_restaurant():
    db = make_db()
    db.add(Restaurant(restaurant_id="spice-box", name="Spice Box", active=True))
    user = User(
        firebase_uid="uid-1",
        email="owner@example.com",
        role="owner",
        restaurant_id="spice-box",
    )
    db.add(user)
    db.commit()

    restaurant = _require_restaurant(user, db)
    assert restaurant.restaurant_id == "spice-box"


def test_unassigned_user_cannot_manage_menu_or_qr():
    db = make_db()
    user = User(
        firebase_uid="uid-2",
        email="new@example.com",
        role="owner",
        restaurant_id=None,
    )
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

def test_create_restaurant_persists_user_association():
    db = make_db()
    user = User(
        firebase_uid="uid-3",
        email="chef@example.com",
        role="owner",
        restaurant_id=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Detach user to simulate different DB session lifecycle from auth dependency
    db.expunge(user)

    from app.schemas.qr_admin import RestaurantCreateRequest
    from app.api.v1.qr_ordering import create_restaurant

    payload = RestaurantCreateRequest(name="Spice Box")
    response = create_restaurant(payload=payload, db=db, current_user=user)

    assert response.name == "Spice Box"
    assert response.restaurant_id.startswith("spice-box-")

    # Verify user in database now has restaurant_id persisted
    persisted_user = db.query(User).filter(User.firebase_uid == "uid-3").first()
    assert persisted_user.restaurant_id == response.restaurant_id
