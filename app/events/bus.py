"""
The in-process domain event bus.

`publish()` is called from within service-layer functions, inside the
same DB transaction as the state change that triggered it (it does
`db.add()`, not `db.commit()` -- the caller's existing commit covers
it). This is what makes the outbox transactional: the event write can
never succeed without the business state change also succeeding, and
vice versa.

Handlers are registered by event type and run entirely inside the
background worker (see worker.py), never inline in the request path --
so a slow or failing notification/webhook can never slow down or break
the API request that triggered it.
"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.events.models import OutboxEvent


class EventType:
    LEAD_CREATED = "lead.created"
    QUOTE_SENT = "quote.sent"
    QUOTE_ACCEPTED = "quote.accepted"
    QUOTE_REJECTED = "quote.rejected"
    JOB_ASSIGNED = "job.assigned"
    JOB_RESCHEDULED = "job.rescheduled"
    JOB_COMPLETED = "job.completed"
    INVOICE_CREATED = "invoice.created"
    INVOICE_OVERDUE = "invoice.overdue"
    PAYMENT_RECORDED = "payment.recorded"
    CONTRACT_EXPIRING = "contract.expiring"
    FEEDBACK_RECEIVED = "feedback.received"


def publish(db: Session, event_type: str, payload: dict) -> OutboxEvent:
    """Queue a domain event for reliable, asynchronous processing.
    Never raises for downstream-handler problems -- those are the
    background worker's concern (with retries), not the caller's."""
    event = OutboxEvent(event_type=event_type, payload=payload, status="PENDING", next_attempt_at=datetime.utcnow())
    db.add(event)
    return event
