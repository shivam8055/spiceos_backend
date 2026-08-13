from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.inventory_item import InventoryItem
from app.models.user import User
from app.schemas.inventory import InventoryItemCreate, InventoryItemResponse

router = APIRouter()


@router.get("/", response_model=list[InventoryItemResponse])
def get_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return (
        db.query(InventoryItem)
        .filter(InventoryItem.is_active.is_(True))
        .order_by(InventoryItem.name.asc())
        .all()
    )


@router.get("/low-stock", response_model=list[InventoryItemResponse])
def get_low_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return (
        db.query(InventoryItem)
        .filter(
            InventoryItem.is_active.is_(True),
            InventoryItem.quantity <= InventoryItem.reorder_level,
        )
        .order_by(InventoryItem.quantity.asc())
        .all()
    )


@router.post(
    "/",
    response_model=InventoryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory_item(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    item = InventoryItem(
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
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An inventory item with this SKU already exists.",
        ) from exc

    return item
