from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.inventory_item import InventoryItem
from app.models.inventory_movement import InventoryMovement
from app.models.user import User
from app.schemas.inventory import (
    InventoryAdjustment,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryMovementResponse,
)

router = APIRouter()


def _require_restaurant_id(current_user: User) -> str:
    if not current_user.restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not associated with a restaurant.",
        )
    return current_user.restaurant_id


@router.get("/", response_model=list[InventoryItemResponse])
def get_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _require_restaurant_id(current_user)
    return (
        db.query(InventoryItem)
        .filter(
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.is_active.is_(True),
        )
        .order_by(InventoryItem.name.asc())
        .all()
    )


@router.get("/low-stock", response_model=list[InventoryItemResponse])
def get_low_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _require_restaurant_id(current_user)
    return (
        db.query(InventoryItem)
        .filter(
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.is_active.is_(True),
            InventoryItem.quantity <= InventoryItem.reorder_level,
        )
        .order_by(InventoryItem.quantity.asc())
        .all()
    )


@router.post("/", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
def create_inventory_item(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _require_restaurant_id(current_user)
    item = InventoryItem(
        restaurant_id=restaurant_id,
        name=payload.name.strip(),
        sku=payload.sku.strip() if payload.sku else None,
        unit=payload.unit.strip(),
        quantity=payload.quantity,
        reorder_level=payload.reorder_level,
        cost_per_unit=payload.cost_per_unit,
        is_active=True,
    )

    db.add(item)
    try:
        db.flush()
        if payload.quantity > 0:
            db.add(
                InventoryMovement(
                    inventory_item_id=item.id,
                    quantity_delta=payload.quantity,
                    reason="Opening stock",
                    created_by_user_id=current_user.id,
                )
            )
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An inventory item with this SKU already exists.",
        ) from exc

    return item


@router.post("/{item_id}/adjust", response_model=InventoryItemResponse)
def adjust_inventory(
    item_id: int,
    payload: InventoryAdjustment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _require_restaurant_id(current_user)
    if payload.quantity_delta == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity adjustment cannot be zero.",
        )

    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.id == item_id,
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.is_active.is_(True),
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found.")

    new_quantity = item.quantity + payload.quantity_delta
    if new_quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock. Current quantity is {item.quantity:g} {item.unit}.",
        )

    movement = InventoryMovement(
        inventory_item_id=item.id,
        quantity_delta=payload.quantity_delta,
        reason=payload.reason.strip(),
        created_by_user_id=current_user.id,
    )
    item.quantity = new_quantity
    db.add(movement)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}/movements", response_model=list[InventoryMovementResponse])
def get_inventory_movements(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _require_restaurant_id(current_user)
    item_exists = (
        db.query(InventoryItem.id)
        .filter(
            InventoryItem.id == item_id,
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.is_active.is_(True),
        )
        .first()
    )
    if item_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found.")

    return (
        db.query(InventoryMovement)
        .filter(InventoryMovement.inventory_item_id == item_id)
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .all()
    )
