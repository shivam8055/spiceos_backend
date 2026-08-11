from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    firebase_uid: str
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime