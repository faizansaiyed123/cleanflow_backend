from datetime import datetime
from pydantic import BaseModel, HttpUrl

from app.events.bus import EventType

ALL_EVENT_TYPES = [v for k, v in vars(EventType).items() if not k.startswith("_")]


class WebhookEndpointCreate(BaseModel):
    url: str
    subscribed_events: list[str]
    description: str | None = None


class WebhookEndpointOut(BaseModel):
    id: str
    url: str
    subscribed_events: list[str]
    is_active: bool
    description: str | None
    created_at: datetime
    # secret is intentionally NOT included here -- shown once, at creation,
    # in WebhookEndpointCreatedOut. A receiver only ever needs it once to
    # configure signature verification; re-displaying it on every GET
    # would make it just another piece of data an XSS or a shoulder-surf
    # could exfiltrate long after the legitimate setup moment has passed.

    class Config:
        from_attributes = True


class WebhookEndpointCreatedOut(WebhookEndpointOut):
    secret: str


class WebhookDeliveryOut(BaseModel):
    id: str
    event_type: str
    status: str
    attempts: int
    max_attempts: int
    last_response_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
