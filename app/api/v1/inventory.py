from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.inventory_item import InventoryItem
from app.models.user import User
from app.schemas.inventory import InventoryItemResponse

router = APIRouter()


@router.get("/", response_model=list[InventoryItemResponse])
def get_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return db.query(InventoryItem).filter(InventoryItem.is_active.is_(True)).order_by(InventoryItem.name.asc()).all()


@router.get("/low-stock", response_model=list[InventoryItemResponse])
def get_low_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return db.query(InventoryItem).filter(InventoryItem.is_active.is_(True), InventoryItem.quantity <= InventoryItem.reorder_level).order_by(InventoryItem.quantity.asc()).all()
