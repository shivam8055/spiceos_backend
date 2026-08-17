import json
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.database import get_db
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.qr_table import QRTable
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.menu_import import MenuImportConfirmRequest, MenuImportConfirmResponse, MenuImportPreviewResponse
from app.schemas.payment import QRPaymentCreateResponse, QRPaymentStatusResponse, QRPaymentVerifyRequest
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
from app.services.razorpay_payment_service import create_qr_payment, process_webhook, verify_checkout_signature
from app.services.qr_ordering import create_qr_order, get_public_order_status, hash_token, menu_response, qr_url, resolve_qr_table

router = APIRouter()


def _managed_user(current_user: User, db: Session) -> User:
    user = db.query(User).filter(User.id == current_user.id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated user profile no longer exists.")
    return user


def _require_restaurant(current_user: User, db: Session) -> Restaurant:
    managed_user = _managed_user(current_user, db)
    restaurant_id = managed_user.restaurant_id
    if not restaurant_id and managed_user.role == "owner":
        claimed_ids = db.query(User.restaurant_id).filter(User.restaurant_id.isnot(None)).subquery()
        candidates = (
            db.query(Restaurant)
            .filter(Restaurant.active.is_(True), ~Restaurant.restaurant_id.in_(claimed_ids))
            .order_by(Restaurant.created_at.desc())
            .all()
        )
        if len(candidates) == 1:
            managed_user.restaurant_id = candidates[0].restaurant_id
            db.commit()
            db.refresh(managed_user)
            restaurant_id = managed_user.restaurant_id

    if not restaurant_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is not associated with a restaurant. Create or join a restaurant first.")

    restaurant = db.query(Restaurant).filter(Restaurant.restaurant_id == restaurant_id, Restaurant.active.is_(True)).first()
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


@router.post("/public/orders/{public_token}/payment", response_model=QRPaymentCreateResponse)
def create_public_payment(public_token: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.public_token_hash == hash_token(public_token), Order.order_source == "qr_table").first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return create_qr_payment(db, order)


@router.post("/public/orders/{public_token}/payment/verify", response_model=QRPaymentStatusResponse)
def verify_public_payment(public_token: str, payload: QRPaymentVerifyRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.public_token_hash == hash_token(public_token), Order.order_source == "qr_table").first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    payment = verify_checkout_signature(db, order, payload.provider_order_id, payload.provider_payment_id, payload.signature)
    return QRPaymentStatusResponse(
        order_id=order.id,
        order_number=order.order_number,
        payment_id=payment.id,
        provider=payment.provider,
        provider_order_id=payment.provider_order_id,
        provider_payment_id=payment.provider_payment_id,
        amount_paise=payment.amount_paise,
        currency=payment.currency,
        status=payment.status,
        provider_status=payment.provider_status,
        created_at=payment.created_at,
        captured_at=payment.captured_at,
        refunded_at=payment.refunded_at,
    )


@router.post("/public/payments/razorpay/webhook")
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"), x_razorpay_event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"), db: Session = Depends(get_db)):
    if not x_razorpay_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing webhook signature.")
    raw_body = await request.body()
    process_webhook(db, raw_body, x_razorpay_signature, x_razorpay_event_id or "")
    return {"ok": True}


@router.post("/admin/restaurant", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
def create_restaurant(payload: RestaurantCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    managed_user = _managed_user(current_user, db)
    if managed_user.restaurant_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already associated with a restaurant.")
    name = payload.name.strip()
    if managed_user.role == "owner":
        existing = db.query(Restaurant).filter(Restaurant.name == name, Restaurant.active.is_(True)).first()
        if existing is not None:
            managed_user.restaurant_id = existing.restaurant_id
            db.commit()
            db.refresh(existing)
            return RestaurantResponse(restaurant_id=existing.restaurant_id, name=existing.name, logo_url=existing.logo_url, active=existing.active)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "restaurant"
    restaurant_id = f"{slug}-{uuid.uuid4().hex[:8]}"
    restaurant = Restaurant(restaurant_id=restaurant_id, name=name, logo_url=payload.logo_url.strip() if payload.logo_url else None, active=True)
    db.add(restaurant)
    managed_user.restaurant_id = restaurant_id
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
async def preview_menu_import(restaurant_id: str = Form(...), branch_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
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
