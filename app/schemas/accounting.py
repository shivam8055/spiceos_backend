from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SalesInvoiceCreate(BaseModel):
    order_id: int | None = None
    customer_name: str = Field(default="Walk-in Customer", min_length=1, max_length=255)
    customer_phone: str | None = None
    customer_gstin: str | None = Field(default=None, max_length=15)
    invoice_date: datetime | None = None
    subtotal: float = Field(ge=0)
    cgst: float = Field(default=0, ge=0)
    sgst: float = Field(default=0, ge=0)
    igst: float = Field(default=0, ge=0)
    discount: float = Field(default=0, ge=0)
    total: float = Field(ge=0)
    payment_status: str = Field(default="pending", pattern="^(pending|paid|refunded)$")
    notes: str | None = None


class SalesInvoiceResponse(SalesInvoiceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: str
    invoice_number: str
    status: str
    created_by_user_id: int


class PurchaseInvoiceCreate(BaseModel):
    bill_number: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=255)
    vendor_gstin: str | None = Field(default=None, max_length=15)
    invoice_date: datetime | None = None
    due_date: datetime | None = None
    subtotal: float = Field(ge=0)
    cgst: float = Field(default=0, ge=0)
    sgst: float = Field(default=0, ge=0)
    igst: float = Field(default=0, ge=0)
    total: float = Field(ge=0)
    payment_status: str = Field(default="unpaid", pattern="^(unpaid|paid|partial)$")
    attachment_url: str | None = None
    notes: str | None = None


class PurchaseInvoiceResponse(PurchaseInvoiceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: str
    created_by_user_id: int


class PurchaseInvoicePaymentUpdate(BaseModel):
    payment_status: str = Field(pattern="^(unpaid|paid|partial)$")


class ExpenseCreate(BaseModel):
    expense_date: datetime | None = None
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=255)
    amount: float = Field(gt=0)
    gst_amount: float = Field(default=0, ge=0)
    payment_mode: str = Field(default="cash", min_length=1, max_length=30)
    reference: str | None = Field(default=None, max_length=100)


class ExpenseResponse(ExpenseCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: str
    created_by_user_id: int


class GSTSummary(BaseModel):
    period_start: datetime
    period_end: datetime
    sales_count: int
    sales_taxable: float
    output_cgst: float
    output_sgst: float
    output_igst: float
    purchase_count: int
    purchase_taxable: float
    input_cgst: float
    input_sgst: float
    input_igst: float
    estimated_net_cgst: float
    estimated_net_sgst: float
    estimated_net_igst: float
    total_sales: float
    total_purchases: float
    total_expenses: float


class GSTProfileBase(BaseModel):
    legal_name: str = Field(default="", max_length=255)
    trade_name: str = Field(default="", max_length=255)
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    business_type: str = Field(default="Proprietorship", max_length=50)
    state: str = Field(default="Bihar", max_length=100)
    state_code: str = Field(default="10", max_length=2)
    address: str | None = None
    pincode: str | None = Field(default=None, max_length=6)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    filing_frequency: str = Field(default="Monthly", max_length=30)
    composition_scheme: bool = False


class GSTProfileUpdate(GSTProfileBase):
    pass


class GSTProfileResponse(GSTProfileBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    restaurant_id: str
    updated_at: datetime
