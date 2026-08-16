from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import require_owner
from app.core.database import get_db
from app.models.user import User

router = APIRouter()


class UserAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    firebase_uid: str
    email: str
    name: str | None
    role: str
    is_active: bool


class UserRoleUpdate(BaseModel):
    role: str


VALID_ROLES = {"owner", "manager", "staff"}


@router.get("/", response_model=list[UserAdminResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    return db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()


@router.patch("/{user_id}/role", response_model=UserAdminResponse)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    role = payload.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid role. Allowed roles: owner, manager, staff.",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if user.id == current_user.id and role != "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current owner cannot remove their own owner role.",
        )

    user.role = role
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserAdminResponse)
def update_user_status(
    user_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if user.id == current_user.id and not is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current owner cannot deactivate their own account.",
        )

    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user
