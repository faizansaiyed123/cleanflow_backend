from datetime import datetime
from pydantic import BaseModel
from app.common.enums import NotificationType


class NotificationOut(BaseModel):
    id: str
    type: NotificationType
    title: str
    body: str | None
    link_entity_type: str | None
    link_entity_id: str | None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
