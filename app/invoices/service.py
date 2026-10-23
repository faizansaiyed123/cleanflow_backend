from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.common.enums import InvoiceStatus, InvoiceSourceType, JobStatus
from app.common.exceptions import ConflictError, ValidationAppError
from app.common.reference_numbers import next_reference
from app.audit.service import record_audit
from app.invoices.models import Invoice, InvoiceItem
from app.jobs.models import Job
from app.notifications.service import notify_user
from app.events.bus import publish, EventType
from app.customers.models import Customer


def _recompute_totals(invoice: Invoice, discount_amount: float, tax_rate_percent: float) -> None:
    subtotal = sum(item.amount for item in invoice.items)
    tax = subtotal * (tax_rate_percent / 100)
    invoice.subtotal = round(subtotal, 2)
    invoice.discount_amount = round(discount_amount, 2)
    invoice.tax_amount = round(tax, 2)
    invoice.total = round(subtotal - discount_amount + tax, 2)


def create_manual_invoice(db: Session, payload, actor) -> Invoice:
    reference = next_reference(db, "invoice")
    invoice = Invoice(
        reference_number=reference,
        customer_id=payload.customer_id,
        property_id=payload.property_id,
        contract_id=payload.contract_id,
        source_type=InvoiceSourceType.MANUAL,
        status=InvoiceStatus.DRAFT,
        due_date=datetime.utcnow() + timedelta(days=payload.due_in_days),
        notes=payload.notes,
    )
    db.add(invoice)
    db.flush()
    for item in payload.items:
        db.add(InvoiceItem(invoice_id=invoice.id, description=item.description, amount=item.amount, job_id=item.job_id))
    db.flush()
    invoice.items  # noqa: touch relationship to load
    db.refresh(invoice)
    _recompute_totals(invoice, payload.discount_amount, payload.tax_rate_percent)
    record_audit(db, actor, "invoice.created", "Invoice", invoice.id, new_state={"total": invoice.total})
    return invoice


def create_invoice_from_job(db: Session, job: Job, due_in_days: int, tax_rate_percent: float, actor) -> Invoice:
    if job.status != JobStatus.COMPLETED:
        raise ConflictError("Only a completed job can be invoiced")
    existing = db.query(InvoiceItem).filter(InvoiceItem.job_id == job.id).first()
    if existing:
        raise ConflictError("This job has already been invoiced")

    contract_service_price = None
    if job.contract and job.contract.services:
        contract_service_price = job.contract.services[0].price

    reference = next_reference(db, "invoice")
    invoice = Invoice(
        reference_number=reference,
        customer_id=job.customer_id,
        property_id=job.property_id,
        contract_id=job.contract_id,
        source_type=InvoiceSourceType.JOB,
        status=InvoiceStatus.DRAFT,
        due_date=datetime.utcnow() + timedelta(days=due_in_days),
    )
    db.add(invoice)
    db.flush()
    amount = contract_service_price if contract_service_price is not None else (job.contract.monthly_value if job.contract else 0.0)
    db.add(InvoiceItem(invoice_id=invoice.id, job_id=job.id,
                        description=f"Cleaning service - {job.reference_number} ({job.scheduled_start.strftime('%b %d, %Y')})",
                        amount=amount))
    db.flush()
    db.refresh(invoice)
    _recompute_totals(invoice, 0.0, tax_rate_percent)
    record_audit(db, actor, "invoice.created", "Invoice", invoice.id, new_state={"from_job": job.id, "total": invoice.total})
    return invoice


def send_invoice(db: Session, invoice: Invoice, actor) -> Invoice:
    if invoice.status != InvoiceStatus.DRAFT:
        raise ConflictError(f"Only a draft invoice can be sent (current status: {invoice.status.value})")
    invoice.status = InvoiceStatus.SENT
    invoice.sent_at = datetime.utcnow()
    customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    if customer and customer.user:
        publish(db, EventType.INVOICE_CREATED, {
            "invoice_id": invoice.id, "reference_number": invoice.reference_number, "total": invoice.total,
            "due_date_label": invoice.due_date.strftime("%b %d, %Y"), "customer_user_id": customer.user.id,
        })
    record_audit(db, actor, "invoice.sent", "Invoice", invoice.id)
    return invoice


def void_invoice(db: Session, invoice: Invoice, actor) -> Invoice:
    if invoice.amount_paid > 0:
        raise ConflictError("Cannot void an invoice that already has payments recorded against it")
    invoice.status = InvoiceStatus.VOID
    invoice.voided_at = datetime.utcnow()
    record_audit(db, actor, "invoice.voided", "Invoice", invoice.id)
    return invoice


def refresh_overdue_status(db: Session) -> int:
    now = datetime.utcnow()
    overdue = (
        db.query(Invoice)
        .filter(Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]), Invoice.due_date < now)
        .all()
    )
    for inv in overdue:
        inv.status = InvoiceStatus.OVERDUE
    return len(overdue)
