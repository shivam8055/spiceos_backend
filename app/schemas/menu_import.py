from pydantic import BaseModel, Field


class ImportedMenuItem(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    price: float = Field(ge=0)
    available: bool = True


class MenuImportPreviewResponse(BaseModel):
    restaurant_id: str
    branch_id: str
    items: list[ImportedMenuItem]
    warnings: list[str] = Field(default_factory=list)


class MenuImportConfirmRequest(BaseModel):
    restaurant_id: str = Field(min_length=1, max_length=100)
    branch_id: str = Field(min_length=1, max_length=100)
    items: list[ImportedMenuItem] = Field(min_length=1, max_length=500)


class MenuImportConfirmResponse(BaseModel):
    created_count: int
    skipped_count: int
