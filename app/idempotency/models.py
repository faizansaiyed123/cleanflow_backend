from sqlalchemy import Column, String, Integer, JSON, DateTime, UniqueConstraint
from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class IdempotencyKey(Base, UUIDPKMixin, TimestampMixin):
    """
    Stripe-style idempotency: a client sends an `Idempotency-Key` header
    on a mutating request. If the exact same key is replayed (e.g. a
    mobile client retrying after a timed-out response, or a browser
    resubmitting a form on double-click), the server returns the
    original response instead of re-running the operation -- so a
    flaky network can never result in two contracts, two payments, or
    two of anything being created from what the user experienced as
    "I clicked once."

    request_fingerprint guards against the (client bug) case of reusing
    a key for a genuinely different request body -- that's treated as
    an error rather than silently returning the wrong cached response.
    """
    __tablename__ = "idempotency_keys"

    key = Column(String(255), nullable=False, index=True)
    endpoint = Column(String(255), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    response_status_code = Column(Integer, nullable=False)
    response_body = Column(JSON, nullable=False)
    expires_at = Column(DateTime(), nullable=False)

    __table_args__ = (UniqueConstraint("key", "endpoint", name="uq_idempotency_key_endpoint"),)
