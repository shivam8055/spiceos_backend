from typing import Optional

from pydantic import BaseModel, Field


class DeliveryAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)


class DeliveryAgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    status: Optional[str] = None
    is_active: Optional[bool] = None


class DeliveryCreate(BaseModel):
    order_id: int
    delivery_address: str = Field(min_length=1, max_length=2000)
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_phone: Optional[str] = Field(default=None, max_length=40)
    pickup_address: Optional[str] = Field(default=None, max_length=2000)
    provider: str = Field(default="own_agent", min_length=1, max_length=40)


class DeliveryQuoteRequest(BaseModel):
    pickup_address: str = Field(min_length=1, max_length=2000)
    delivery_address: str = Field(min_length=1, max_length=2000)
    provider: str = Field(default="uber_direct", min_length=1, max_length=40)


class DeliveryAssign(BaseModel):
    agent_id: int


class DeliveryStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = Field(default=None, max_length=1000)
    latitude: Optional[str] = Field(default=None, max_length=32)
    longitude: Optional[str] = Field(default=None, max_length=32)


class DeliveryLocationUpdate(BaseModel):
    latitude: str = Field(max_length=32)
    longitude: str = Field(max_length=32)


class DeliveryProviderCreate(BaseModel):
    provider: str = Field(default="own_agent", min_length=1, max_length=40)


class PublicDeliveryStatus(BaseModel):
    delivery_token: str
    status: str
    provider: str
    eta_minutes: Optional[int] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
