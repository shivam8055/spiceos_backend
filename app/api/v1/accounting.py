from calendar import monthrange
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import require_manager, require_staff
from app.core.database import get_db
from app.models.accounting import Expense, PurchaseInvoice, SalesInvoice
from app.models.user import User
from app.schemas.accounting import (
    ExpenseCreate,
    ExpenseResponse,
    GSTSummary,
    PurchaseInvoiceCreate,
    PurchaseInvoiceResponse,
    SalesInvoiceCreate,
    SalesInvoiceResponse,
)

router = APIRouter(prefix="/accounting", tags=["accounting"])


def _restaurant_id(user: User) -> str:
    if not user.restaurant_id:
        raise HTTPException(status_code=409, detail="User is not associated with a restaurant.")
    return user.restaurant_id


def _next_invoice_number(db: Session, restaurant_id: str, when: datetime) -> str:
    prefix = f"INV-{when:%Y%m}-"
    count = db.query(func.count(SalesInvoice.id)).filter(
        SalesInvoice.restaurant_id == restaurant_id,
        SalesInvoice.invoice_number.like(f"{prefix}%"),
    ).scalar() or 0
    return f"{prefix}{count + 1:05d}"


@router.post("/sales-invoices", response_model=SalesInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_sales_invoice(payload: SalesInvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    restaurant_id = _restaurant_id(user)
    when = payload.invoice_date or datetime.utcnow()
    invoice = SalesInvoice(
        restaurant_id=restaurant_id,
        invoice_number=_next_invoice_number(db, restaurant_id, when),
        order_id=payload.order_id,
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone,
        customer_gstin=payload.customer_gstin,
        invoice_date=when,
        subtotal=payload.subtotal,
        cgst=payload.cgst,
        sgst=payload.sgst,
        igst=payload.igst,
        discount=payload.discount,
        total=payload.total,
        payment_status=payload.payment_status,
        status="issued",
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/sales-invoices", response_model=list[SalesInvoiceResponse])
def list_sales_invoices(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return db.query(SalesInvoice).filter(SalesInvoice.restaurant_id == _restaurant_id(user)).order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc()).limit(limit).all()


@router.post("/purchase-invoices", response_model=PurchaseInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_invoice(payload: PurchaseInvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    restaurant_id = _restaurant_id(user)
    duplicate = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.restaurant_id == restaurant_id,
        PurchaseInvoice.bill_number == payload.bill_number.strip(),
        PurchaseInvoice.vendor_name == payload.vendor_name.strip(),
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="This vendor bill is already recorded.")
    invoice = PurchaseInvoice(
        restaurant_id=restaurant_id,
        bill_number=payload.bill_number.strip(),
        vendor_name=payload.vendor_name.strip(),
        vendor_gstin=payload.vendor_gstin,
        invoice_date=payload.invoice_date or datetime.utcnow(),
        due_date=payload.due_date,
        subtotal=payload.subtotal,
        cgst=payload.cgst,
        sgst=payload.sgst,
        igst=payload.igst,
        total=payload.total,
        payment_status=payload.payment_status,
        attachment_url=payload.attachment_url,
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/purchase-invoices", response_model=list[PurchaseInvoiceResponse])
def list_purchase_invoices(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return db.query(PurchaseInvoice).filter(PurchaseInvoice.restaurant_id == _restaurant_id(user)).order_by(PurchaseInvoice.invoice_date.desc(), PurchaseInvoice.id.desc()).limit(limit).all()


@router.post("/expenses", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    expense = Expense(
        restaurant_id=_restaurant_id(user),
        expense_date=payload.expense_date or datetime.utcnow(),
        category=payload.category.strip(),
        description=payload.description.strip(),
        amount=payload.amount,
        gst_amount=payload.gst_amount,
        payment_mode=payload.payment_mode.strip(),
        reference=payload.reference,
        created_by_user_id=user.id,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/expenses", response_model=list[ExpenseResponse])
def list_expenses(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    return db.query(Expense).filter(Expense.restaurant_id == _restaurant_id(user)).order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit).all()


@router.get("/gst-summary", response_model=GSTSummary)
def gst_summary(
    year: int = Query(default=0, ge=0),
    month: int = Query(default=0, ge=0, le=12),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    now = datetime.utcnow()
    year = year or now.year
    month = month or now.month
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    start = datetime(year, month, 1)
    rid = _restaurant_id(user)

    sales = db.query(SalesInvoice).filter(SalesInvoice.restaurant_id == rid, SalesInvoice.invoice_date >= start, SalesInvoice.invoice_date < end, SalesInvoice.status == "issued").all()
    purchases = db.query(PurchaseInvoice).filter(PurchaseInvoice.restaurant_id == rid, PurchaseInvoice.invoice_date >= start, PurchaseInvoice.invoice_date < end).all()
    expenses = db.query(Expense).filter(Expense.restaurant_id == rid, Expense.expense_date >= start, Expense.expense_date < end).all()

    output_cgst = sum(x.cgst for x in sales)
    output_sgst = sum(x.sgst for x in sales)
    output_igst = sum(x.igst for x in sales)
    input_cgst = sum(x.cgst for x in purchases)
    input_sgst = sum(x.sgst for x in purchases)
    input_igst = sum(x.igst for x in purchases)

    return GSTSummary(
        period_start=start,
        period_end=end - timedelta(microseconds=1),
        sales_count=len(sales),
        sales_taxable=sum(max(0, x.subtotal - x.discount) for x in sales),
        output_cgst=output_cgst,
        output_sgst=output_sgst,
        output_igst=output_igst,
        purchase_count=len(purchases),
        purchase_taxable=sum(x.subtotal for x in purchases),
        input_cgst=input_cgst,
        input_sgst=input_sgst,
        input_igst=input_igst,
        estimated_net_cgst=max(0, output_cgst - input_cgst),
        estimated_net_sgst=max(0, output_sgst - input_sgst),
        estimated_net_igst=max(0, output_igst - input_igst),
        total_sales=sum(x.total for x in sales),
        total_purchases=sum(x.total for x in purchases),
        total_expenses=sum(x.amount for x in expenses),
    )
