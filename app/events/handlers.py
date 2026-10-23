"""
Event handlers: pure functions from (db, payload) -> side effects,
invoked exclusively by the background worker (never inline in a
request). Adding a new reaction to an existing event means adding a
line here -- the code that raises the event never needs to change,
which is the whole point of decoupling via an event bus.
"""
from sqlalchemy.orm import Session

from app.events.bus import EventType
from app.notifications.service import notify_user, notify_role
from app.webhooks.service import enqueue_deliveries_for_event
from app.feature_flags.service import is_enabled


def handle_lead_created(db: Session, payload: dict):
    notify_role(db, "STAFF", "NEW_LEAD", f"New lead {payload['reference_number']}",
                f"{payload['contact_name']} requested a quote via the website.", "Lead", payload["lead_id"])


def handle_quote_sent(db: Session, payload: dict):
    if payload.get("customer_user_id"):
        notify_user(db, payload["customer_user_id"], "QUOTE_CREATED", f"New quote {payload['reference_number']}",
                    f"You have a new quote for ${payload['total']:.2f}.", "Quote", payload["quote_id"])


def handle_quote_accepted(db: Session, payload: dict):
    notify_role(db, "STAFF", "QUOTE_ACCEPTED", f"Quote {payload['reference_number']} accepted",
                "A customer accepted their quote. A contract and schedule have been created.",
                "Contract", payload["contract_id"])


def handle_quote_rejected(db: Session, payload: dict):
    notify_role(db, "STAFF", "QUOTE_REJECTED", f"Quote {payload['reference_number']} rejected",
                payload.get("reason"), "Quote", payload["quote_id"])


def handle_job_assigned(db: Session, payload: dict):
    for emp_user_id in payload.get("employee_user_ids", []):
        notify_user(db, emp_user_id, "JOB_ASSIGNED", f"New job assigned: {payload['reference_number']}",
                    payload.get("scheduled_start_label"), "Job", payload["job_id"])


def handle_job_rescheduled(db: Session, payload: dict):
    notify_role(db, "STAFF", "JOB_RESCHEDULED", f"Job {payload['reference_number']} rescheduled", None,
                "Job", payload["job_id"])


def handle_job_completed(db: Session, payload: dict):
    notify_role(db, "STAFF", "JOB_COMPLETED", f"Job {payload['reference_number']} completed",
                "Proof of service and checklist confirmed complete.", "Job", payload["job_id"])

    # Feature-flag-gated automation: this is exactly the kind of side
    # effect the outbox pattern exists for -- it runs asynchronously,
    # can be retried independently of the job-completion request, and
    # can be toggled off instantly without a deploy if it misbehaves.
    if is_enabled(db, "auto_invoice_on_completion"):
        from app.jobs.models import Job
        from app.invoices.models import InvoiceItem
        from app.invoices.service import create_invoice_from_job, send_invoice
        from app.common.exceptions import ConflictError

        job = db.query(Job).filter(Job.id == payload["job_id"]).first()
        if job and not db.query(InvoiceItem).filter(InvoiceItem.job_id == job.id).first():
            try:
                invoice = create_invoice_from_job(db, job, due_in_days=15, tax_rate_percent=0.0, actor=None)
                send_invoice(db, invoice, None)
            except ConflictError:
                pass  # already invoiced by a manager in the meantime -- not an error


def handle_invoice_created(db: Session, payload: dict):
    if payload.get("customer_user_id"):
        notify_user(db, payload["customer_user_id"], "INVOICE_CREATED", f"New invoice {payload['reference_number']}",
                    f"${payload['total']:.2f} due {payload['due_date_label']}", "Invoice", payload["invoice_id"])


def handle_invoice_overdue(db: Session, payload: dict):
    notify_role(db, "STAFF", "INVOICE_OVERDUE", f"Invoice {payload['reference_number']} is overdue",
                None, "Invoice", payload["invoice_id"])


def handle_payment_recorded(db: Session, payload: dict):
    if payload.get("customer_user_id"):
        notify_user(db, payload["customer_user_id"], "PAYMENT_RECEIVED",
                    f"Payment received — ${payload['amount']:.2f}", None, "Invoice", payload["invoice_id"])


def handle_contract_expiring(db: Session, payload: dict):
    notify_role(db, "STAFF", "CONTRACT_EXPIRING", f"Contract {payload['reference_number']} expiring soon",
                None, "Contract", payload["contract_id"])


def handle_feedback_received(db: Session, payload: dict):
    notify_role(db, "STAFF", "FEEDBACK_RECEIVED", f"New {payload['rating']}-star feedback",
                payload.get("comment"), "Feedback", payload["feedback_id"])


HANDLERS = {
    EventType.LEAD_CREATED: handle_lead_created,
    EventType.QUOTE_SENT: handle_quote_sent,
    EventType.QUOTE_ACCEPTED: handle_quote_accepted,
    EventType.QUOTE_REJECTED: handle_quote_rejected,
    EventType.JOB_ASSIGNED: handle_job_assigned,
    EventType.JOB_RESCHEDULED: handle_job_rescheduled,
    EventType.JOB_COMPLETED: handle_job_completed,
    EventType.INVOICE_CREATED: handle_invoice_created,
    EventType.INVOICE_OVERDUE: handle_invoice_overdue,
    EventType.PAYMENT_RECORDED: handle_payment_recorded,
    EventType.CONTRACT_EXPIRING: handle_contract_expiring,
    EventType.FEEDBACK_RECEIVED: handle_feedback_received,
}


def dispatch(db: Session, event_type: str, payload: dict) -> None:
    """Run the in-app-notification side effect for one event, then fan
    it out to any subscribed webhook endpoints. Both are best-effort at
    this layer -- the worker (see worker.py) is what handles retries."""
    handler = HANDLERS.get(event_type)
    if handler:
        handler(db, payload)
    enqueue_deliveries_for_event(db, event_type, payload, outbox_event_id=payload.get("_outbox_event_id"))
