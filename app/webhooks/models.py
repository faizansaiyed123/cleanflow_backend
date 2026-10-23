from sqlalchemy import Column, String, Boolean, JSON, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class WebhookEndpoint(Base, UUIDPKMixin, TimestampMixin):
    """A company-configured outbound webhook subscription -- lets an
    external system (a Slack relay, a BI tool, a custom integration)
    receive real-time domain events without polling the API. No
    third-party service is required to use this: it POSTs to whatever
    URL the owner configures, including one they run themselves."""

    __tablename__ = "webhook_endpoints"

    url = Column(String(1000), nullable=False)
    # HMAC-SHA256 signing secret -- generated on creation, shown once.
    # Receivers verify the X-CleanFlow-Signature header against the raw
    # body using this secret, the same pattern Stripe/GitHub webhooks use.
    secret = Column(String(100), nullable=False)
    subscribed_events = Column(JSON, nullable=False, default=list)  # e.g. ["job.completed", "invoice.overdue"]
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(String(255), nullable=True)

    deliveries = relationship("WebhookDelivery", back_populates="endpoint", cascade="all, delete-orphan")


class WebhookDelivery(Base, UUIDPKMixin, TimestampMixin):
    """One delivery attempt lifecycle for one event to one endpoint.
    Kept as its own row (rather than a log line) so the retry worker
    has durable state to resume from after a crash/restart."""

    __tablename__ = "webhook_deliveries"

    endpoint_id = Column(String(36), ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    outbox_event_id = Column(String(36), ForeignKey("outbox_events.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)

    status = Column(String(20), nullable=False, default="PENDING", index=True)  # PENDING|SENT|FAILED|DEAD_LETTER
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=6)
    next_attempt_at = Column(DateTime(), nullable=True)
    last_response_code = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    delivered_at = Column(DateTime(), nullable=True)

    endpoint = relationship("WebhookEndpoint", back_populates="deliveries")
