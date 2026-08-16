from pydantic import BaseModel, Field


class QRContextResponse(BaseModel):
    restaurant_id: str
    branch_id: str
    table_id: str
    table_name: str
    session_id: str


class QRModifierResponse(BaseModel):
    id: str
    name: str
    price_delta: float
    available: bool


class QRMenuItemResponse(BaseModel):
    id: int
    category: str
    name: str
    description: str | None
    price: float
    available: bool
    modifiers: list[QRModifierResponse]


class QRMenuResponse(BaseModel):
    context: QRContextResponse
    categories: list[str]
    items: list[QRMenuItemResponse]


class QROrderItemRequest(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1, le=50)
    modifier_ids: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class QROrderCreateRequest(BaseModel):
    items: list[QROrderItemRequest] = Field(min_length=1, max_length=50)
    customer_name: str | None = Field(default=None, max_length=100)
    customer_phone: str | None = Field(default=None, max_length=20)


class QROrderCreateResponse(BaseModel):
    order_id: int
    order_number: str
    status: str
    total: float
    currency: str
    table_name: str
    public_order_token: str


class QROrderStatusResponse(BaseModel):
    order_number: str
    status: str
    total: float
    currency: str
    table_name: str
    created_at: str
