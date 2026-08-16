import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.menu_item import MenuItem
from app.models.qr_table import QRTable
from app.models.user import User
from app.schemas.qr_admin import (
    MenuItemCreateRequest,
    MenuItemCreateResponse,
    QRTableCreateRequest,
    QRTableCreateResponse,
)
from app.schemas.qr_ordering import QROrderCreateRequest, QROrderCreateResponse, QRMenuResponse, QROrderStatusResponse
from app.services.qr_ordering import create_qr_order, get_public_order_status, hash_token, menu_response, qr_url, resolve_qr_table

router = APIRouter()


@router.get("/public/qr/{token}/menu", response_model=QRMenuResponse)
def get_public_menu(token: str, db: Session = Depends(get_db)):
    table = resolve_qr_table(db, token)
    return menu_response(db, table)


@router.post("/public/qr/{token}/orders", response_model=QROrderCreateResponse, status_code=status.HTTP_201_CREATED)
def create_public_order(
    token: str,
    payload: QROrderCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    table = resolve_qr_table(db, token)
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header is required.")
    return create_qr_order(db, table, payload, idempotency_key)


@router.get("/public/orders/{public_token}", response_model=QROrderStatusResponse)
def public_order_status(public_token: str, db: Session = Depends(get_db)):
    return get_public_order_status(db, public_token)


@router.post("/admin/qr-tables", response_model=QRTableCreateResponse, status_code=status.HTTP_201_CREATED)
def create_qr_table(
    payload: QRTableCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    raw_token = secrets.token_urlsafe(32)
    table = QRTable(
        restaurant_id=payload.restaurant_id.strip(),
        branch_id=payload.branch_id.strip(),
        table_id=payload.table_id.strip(),
        table_name=payload.table_name.strip(),
        session_id=payload.session_id.strip(),
        token_hash=hash_token(raw_token),
        active=True,
        expires_at=payload.expires_at,
    )
    db.add(table)
    db.commit()
    db.refresh(table)
    return QRTableCreateResponse(
        id=table.id,
        restaurant_id=table.restaurant_id,
        branch_id=table.branch_id,
        table_id=table.table_id,
        table_name=table.table_name,
        session_id=table.session_id,
        qr_token=raw_token,
        qr_url=qr_url(raw_token),
    )


@router.post("/admin/menu-items", response_model=MenuItemCreateResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item(
    payload: MenuItemCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    item = MenuItem(
        restaurant_id=payload.restaurant_id.strip(),
        branch_id=payload.branch_id.strip(),
        category=payload.category.strip(),
        name=payload.name.strip(),
        description=payload.description,
        price=payload.price,
        available=payload.available,
        modifiers_json=json.dumps([modifier.model_dump() for modifier in payload.modifiers], separators=(",", ":")),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return MenuItemCreateResponse(id=item.id, name=item.name, price=float(item.price))
