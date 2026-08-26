from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.menu_item import MenuItem
from app.models.user import User

router = APIRouter()


def _current_restaurant(current_user: User, db: Session) -> str:
    managed = db.query(User).filter(User.id == current_user.id).first()
    restaurant_id = managed.restaurant_id if managed else None
    if not restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not associated with a restaurant.",
        )
    return restaurant_id


@router.delete("/admin/menu-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_menu_item(
    item_id: int,
    branch_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant_id = _current_restaurant(current_user, db)
    item = (
        db.query(MenuItem)
        .filter(
            MenuItem.id == item_id,
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.branch_id == branch_id.strip(),
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found for this branch.")
    db.delete(item)
    db.commit()
    return None
