from datetime import datetime

from pydantic import BaseModel, Field


class QRPaymentCreateResponse(BaseModel):
    order_id: int
    order_number: str
    payment_id: int
    provider: str
    provider_order_id: str
    amount_paise: int = Field(ge=0)
    currency: str
    key_id: str
    status: str


class QRPaymentVerifyRequest(BaseModel):
    provider_order_id: str = Field(min_length=1)
    provider_payment_id: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class QRPaymentStatusResponse(BaseModel):
    order_id: int
    order_number: str
    payment_id: int
    provider: str
    provider_order_id: str
    provider_payment_id: str | None
    amount_paise: int
    currency: str
    status: str
    provider_status: str | None
    created_at: datetime
    captured_at: datetime | None
    refunded_at: datetime | None
