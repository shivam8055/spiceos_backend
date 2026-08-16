from datetime import datetime

from pydantic import BaseModel, Field


class RestaurantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    logo_url: str | None = Field(default=None, max_length=1000)


class RestaurantResponse(BaseModel):
    restaurant_id: str
    name: str
    logo_url: str | None
    active: bool


class QRTableCreateRequest(BaseModel):
    restaurant_id: str = Field(min_length=1, max_length=100)
    branch_id: str = Field(min_length=1, max_length=100)
    table_id: str = Field(min_length=1, max_length=100)
    table_name: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class QRTableCreateResponse(BaseModel):
    id: int
    restaurant_id: str
    branch_id: str
    table_id: str
    table_name: str
    session_id: str
    qr_token: str
    qr_url: str


class MenuModifierInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    price_delta: float = 0
    available: bool = True


class MenuItemCreateRequest(BaseModel):
    restaurant_id: str = Field(min_length=1, max_length=100)
    branch_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    price: float = Field(ge=0)
    available: bool = True
    modifiers: list[MenuModifierInput] = Field(default_factory=list, max_length=50)


class MenuItemCreateResponse(BaseModel):
    id: int
    name: str
    price: float
