from datetime import datetime
from pydantic import BaseModel


class FeatureFlagOut(BaseModel):
    id: str
    key: str
    is_enabled: bool
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FeatureFlagToggle(BaseModel):
    is_enabled: bool
