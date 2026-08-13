from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InventoryItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=100)
    unit: str = Field(default="unit", min_length=1, max_length=50)
    quantity: float = Field(default=0, ge=0)
    reorder_level: float = Field(default=0, ge=0)
    cost_per_unit: float = Field(default=0, ge=0)


class InventoryItemResponse(InventoryItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class InventoryAdjustment(BaseModel):
    quantity_delta: float
    reason: str = Field(min_length=1, max_length=255)


class InventoryMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_item_id: int
    quantity_delta: float
    reason: str
    created_by_user_id: int
    created_at: datetime
