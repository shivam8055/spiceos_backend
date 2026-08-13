from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    order_number: str = Field(min_length=1)
    customer_id: str | None = None
    customer_name: str = Field(min_length=1)
    primary_item: str | None = None
    total: float = Field(ge=0)
    payment_status: str = "pending"
    order_source: str = "Unknown"


class OrderUpdate(BaseModel):
    customer_id: str | None = None
    customer_name: str | None = Field(default=None, min_length=1)
    primary_item: str | None = None
    total: float | None = Field(default=None, ge=0)
    status: str | None = None
    payment_status: str | None = None
    order_source: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    customer_id: str | None
    customer_name: str
    primary_item: str | None
    created_at: datetime
    status: str
    payment_status: str
    total: float
    order_source: str
