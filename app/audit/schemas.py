from datetime import datetime
from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: str
    actor_user_id: str | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str
    previous_state: dict | None
    new_state: dict | None
    created_at: datetime

    class Config:
        from_attributes = True
