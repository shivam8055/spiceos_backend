from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.database import Base


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(String, nullable=False, index=True)
    invoice_number = Column(String, nullable=False, index=True)
    order_id = Column(Integer, nullable=True, index=True)
    customer_name = Column(String, nullable=False, default="Walk-in Customer")
    customer_phone = Column(String, nullable=True)
    customer_gstin = Column(String, nullable=True)
    invoice_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    subtotal = Column(Float, nullable=False, default=0)
    cgst = Column(Float, nullable=False, default=0)
    sgst = Column(Float, nullable=False, default=0)
    igst = Column(Float, nullable=False, default=0)
    discount = Column(Float, nullable=False, default=0)
    total = Column(Float, nullable=False, default=0)
    payment_status = Column(String, nullable=False, default="pending")
    status = Column(String, nullable=False, default="issued")
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, nullable=False)


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(String, nullable=False, index=True)
    bill_number = Column(String, nullable=False, index=True)
    vendor_name = Column(String, nullable=False)
    vendor_gstin = Column(String, nullable=True)
    invoice_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    due_date = Column(DateTime, nullable=True)
    subtotal = Column(Float, nullable=False, default=0)
    cgst = Column(Float, nullable=False, default=0)
    sgst = Column(Float, nullable=False, default=0)
    igst = Column(Float, nullable=False, default=0)
    total = Column(Float, nullable=False, default=0)
    payment_status = Column(String, nullable=False, default="unpaid")
    attachment_url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(String, nullable=False, index=True)
    expense_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    gst_amount = Column(Float, nullable=False, default=0)
    payment_mode = Column(String, nullable=False, default="cash")
    reference = Column(String, nullable=True)
    created_by_user_id = Column(Integer, nullable=False)
