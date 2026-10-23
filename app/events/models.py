"""
The transactional outbox.

Problem this solves: if a service function both (a) commits a state
change and (b) makes a side-effecting call (send a notification, fire a
webhook, recompute analytics) as two separate operations, a crash
between them leaves the system inconsistent -- the "dual write"
problem. There is no way to atomically write to a database AND publish
to an external channel in one operation.

The fix: side effects are never performed directly. Instead, the
service function writes an OutboxEvent row in the SAME database
transaction as the state change (so it's atomically all-or-nothing),
then returns. A separate background worker (app/events/worker.py)
polls for unprocessed events and dispatches them -- notifications,
webhook deliveries, analytics rollups -- with retries and a dead-letter
state after repeated failures. This gives "at-least-once" delivery of
every domain event without ever risking losing one on a crash.
"""
from sqlalchemy import Column, String, JSON, Integer, DateTime, Boolean, Text
from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class OutboxEvent(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "outbox_events"

    event_type = Column(String(100), nullable=False, index=True)  # e.g. "job.completed"
    payload = Column(JSON, nullable=False)
    # Processing state machine: PENDING -> PROCESSING -> PROCESSED | DEAD_LETTER
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime(), nullable=True)
    last_error = Column(Text, nullable=True)
    processed_at = Column(DateTime(), nullable=True)
