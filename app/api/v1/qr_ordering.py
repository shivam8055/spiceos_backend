import json
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.menu_item import MenuItem
from app.models.qr_table import QRTable
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.menu_import import MenuImportConfirmRequest, MenuImportConfirmResponse, MenuImportPreviewResponse
from app.schemas.qr_admin import (
    MenuItemCreateRequest,
    MenuItemCreateResponse,
    MenuItemResponse,
    QRTableCreateRequest,
    QRTableCreateResponse,
    QRTableListResponse,
    RestaurantCreateRequest,
    RestaurantResponse,
)
from app.schemas.qr_ordering import QROrderCreateRequest, QROrderCreateResponse, QRMenuResponse, QROrderStatusResponse
from app.services.menu_import import MenuImportError, extract_menu_from_image
from app.services.qr_ordering import create_qr_order, get_public_order_status, hash_token, menu_response, qr_url, resolve_qr_table

router = APIRouter()


def _require_restaurant(current_user: User, db: Session) -> Restaurant:
    if not current_user.restaurant_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is not associated with a restaurant. Create or join a restaurant first.")
    restaurant = db.query(Restaurant).filter(Restaurant.restaurant_id == current_user.restaurant_id, Restaurant.active.is_(True)).first()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access is inactive or invalid.")
    return restaurant


def _validate_tenant_payload(payload_restaurant_id: str, restaurant: Restaurant) -> None:
    if payload_restaurant_id.strip() != restaurant.restaurant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot manage another restaurant's resources.")


@router.get("/public/qr/{token}/menu", response_model=QRMenuResponse)
def get_public_menu(token: str, db: Session = Depends(get_db)):
    return menu_response(db, resolve_qr_table(db, token))


@router.post("/public/qr/{token}/orders", response_model=QROrderCreateResponse, status_code=status.HTTP_201_CREATED)
def create_public_order(token: str, payload: QROrderCreateRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), db: Session = Depends(get_db)):
    table = resolve_qr_table(db, token)
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header is required.")
    return create_qr_order(db, table, payload, idempotency_key)


@router.get("/public/orders/{public_token}", response_model=QROrderStatusResponse)
def public_order_status(public_token: str, db: Session = Depends(get_db)):
    return get_public_order_status(db, public_token)


@router.post("/admin/restaurant", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
def create_restaurant(payload: RestaurantCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    if current_user.restaurant_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already associated with a restaurant.")
    slug = re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-") or "restaurant"
    restaurant_id = f"{slug}-{uuid.uuid4().hex[:8]}"
    restaurant = Restaurant(restaurant_id=restaurant_id, name=payload.name.strip(), logo_url=payload.logo_url.strip() if payload.logo_url else None, active=True)
    db.add(restaurant)
    current_user.restaurant_id = restaurant_id
    db.commit()
    db.refresh(restaurant)
    return RestaurantResponse(restaurant_id=restaurant.restaurant_id, name=restaurant.name, logo_url=restaurant.logo_url, active=restaurant.active)


@router.get("/admin/restaurant", response_model=RestaurantResponse)
def get_restaurant(db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    return RestaurantResponse(restaurant_id=restaurant.restaurant_id, name=restaurant.name, logo_url=restaurant.logo_url, active=restaurant.active)


@router.get("/admin/menu-items", response_model=list[MenuItemResponse])
def list_menu_items(restaurant_id: str, branch_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    _validate_tenant_payload(restaurant_id, restaurant)
    items = db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant.restaurant_id, MenuItem.branch_id == branch_id.strip()).order_by(MenuItem.category.asc(), MenuItem.name.asc()).all()
    result = []
    for item in items:
        try:
            modifiers = json.loads(item.modifiers_json or "[]")
        except (TypeError, json.JSONDecodeError):
            modifiers = []
        result.append(MenuItemResponse(id=item.id, restaurant_id=item.restaurant_id, branch_id=item.branch_id, category=item.category, name=item.name, description=item.description, price=float(item.price), available=item.available, modifiers=modifiers))
    return result


@router.post("/admin/menu-import/preview", response_model=MenuImportPreviewResponse)
async def preview_menu_import(
    restaurant_id: str = Form(...),
    branch_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    restaurant = _require_restaurant(current_user, db)
    _validate_tenant_payload(restaurant_id, restaurant)
    try:
        content = await file.read()
        items, warnings = await extract_menu_from_image(content, file.content_type or "")
    except MenuImportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return MenuImportPreviewResponse(restaurant_id=restaurant.restaurant_id, branch_id=branch_id.strip(), items=items, warnings=warnings)


@router.post("/admin/menu-import/confirm", response_model=MenuImportConfirmResponse)
def confirm_menu_import(payload: MenuImportConfirmRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    _validate_tenant_payload(payload.restaurant_id, restaurant)
    created = 0
    skipped = 0
    for imported in payload.items:
        existing = db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant.restaurant_id, MenuItem.branch_id == payload.branch_id.strip(), MenuItem.name == imported.name.strip()).first()
        if existing:
            skipped += 1
            continue
        db.add(MenuItem(restaurant_id=restaurant.restaurant_id, branch_id=payload.branch_id.strip(), category=imported.category.strip(), name=imported.name.strip(), description=imported.description, price=imported.price, available=imported.available, modifiers_json="[]"))
        created += 1
    db.commit()
    return MenuImportConfirmResponse(created_count=created, skipped_count=skipped)


@router.get("/admin/qr-tables", response_model=list[QRTableListResponse])
def list_qr_tables(branch_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    query = db.query(QRTable).filter(QRTable.restaurant_id == restaurant.restaurant_id)
    if branch_id:
        query = query.filter(QRTable.branch_id == branch_id.strip())
    tables = query.order_by(QRTable.branch_id.asc(), QRTable.table_id.asc(), QRTable.created_at.desc()).all()
    return [QRTableListResponse(id=t.id, restaurant_id=t.restaurant_id, branch_id=t.branch_id, table_id=t.table_id, table_name=t.table_name, session_id=t.session_id, active=t.active, expires_at=t.expires_at) for t in tables]


@router.post("/admin/qr-tables", response_model=QRTableCreateResponse, status_code=status.HTTP_201_CREATED)
def create_qr_table(payload: QRTableCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    _validate_tenant_payload(payload.restaurant_id, restaurant)
    branch_id, table_id = payload.branch_id.strip(), payload.table_id.strip()
    table_name, session_id = payload.table_name.strip(), payload.session_id.strip()
    existing = db.query(QRTable).filter(QRTable.restaurant_id == restaurant.restaurant_id, QRTable.branch_id == branch_id, QRTable.table_id == table_id, QRTable.session_id == session_id, QRTable.active.is_(True)).all()
    for old_table in existing:
        old_table.active = False
    raw_token = secrets.token_urlsafe(32)
    table = QRTable(restaurant_id=restaurant.restaurant_id, branch_id=branch_id, table_id=table_id, table_name=table_name, session_id=session_id, token_hash=hash_token(raw_token), active=True, expires_at=payload.expires_at)
    db.add(table)
    db.commit()
    db.refresh(table)
    return QRTableCreateResponse(id=table.id, restaurant_id=table.restaurant_id, branch_id=table.branch_id, table_id=table.table_id, table_name=table.table_name, session_id=table.session_id, qr_token=raw_token, qr_url=qr_url(raw_token))


@router.post("/admin/menu-items", response_model=MenuItemCreateResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item(payload: MenuItemCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    restaurant = _require_restaurant(current_user, db)
    _validate_tenant_payload(payload.restaurant_id, restaurant)
    item = MenuItem(restaurant_id=restaurant.restaurant_id, branch_id=payload.branch_id.strip(), category=payload.category.strip(), name=payload.name.strip(), description=payload.description, price=payload.price, available=payload.available, modifiers_json=json.dumps([modifier.model_dump() for modifier in payload.modifiers], separators=(",", ":")))
    db.add(item)
    db.commit()
    db.refresh(item)
    return MenuItemCreateResponse(id=item.id, name=item.name, price=float(item.price))
