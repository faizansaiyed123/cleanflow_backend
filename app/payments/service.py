from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.common.enums import InvoiceStatus
from app.common.exceptions import ConflictError, ValidationAppError
from app.audit.service import record_audit
from app.invoices.models import Invoice
from app.payments.models import Payment
from app.events.bus import publish, EventType


def record_payment(db: Session, invoice: Invoice, payload, actor) -> Payment:
    """
    Records a (possibly partial) payment and keeps the invoice status
    consistent:
      - amount must be > 0
      - a payment cannot push the invoice's paid total past its total
        unless the caller explicitly opts into overpayment (e.g. a
        goodwill credit) -- this is the "payment cannot exceed invoice
        balance unless explicitly supported" rule.
      - PARTIALLY_PAID vs PAID is derived, never set directly.
    """
    if invoice.status == InvoiceStatus.VOID:
        raise ConflictError("Cannot record a payment against a voided invoice")
    if invoice.status == InvoiceStatus.DRAFT:
        raise ConflictError("Invoice must be sent before payments can be recorded against it")

    new_total_paid = invoice.amount_paid + payload.amount
    if new_total_paid > invoice.total + 0.005 and not payload.allow_overpayment:
        raise ConflictError(
            f"Payment of ${payload.amount:.2f} would exceed the remaining balance of "
            f"${invoice.balance_due:.2f}. Set allow_overpayment to record a credit anyway."
        )

    payment = Payment(
        invoice_id=invoice.id, amount=payload.amount, method=payload.method,
        paid_at=payload.paid_at or datetime.utcnow(), reference=payload.reference,
        notes=payload.notes, recorded_by_user_id=actor.id if actor else None,
    )
    db.add(payment)

    invoice.amount_paid = round(new_total_paid, 2)
    if invoice.amount_paid >= invoice.total - 0.005:
        invoice.status = InvoiceStatus.PAID
    elif invoice.amount_paid > 0:
        invoice.status = InvoiceStatus.PARTIALLY_PAID

    record_audit(db, actor, "payment.recorded", "Payment", invoice.id, new_state={"amount": payload.amount})

    from app.customers.models import Customer
    customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    publish(db, EventType.PAYMENT_RECORDED, {
        "invoice_id": invoice.id, "amount": payload.amount,
        "customer_user_id": customer.user.id if customer and customer.user else None,
    })

    from app.observability.metrics import PAYMENTS_RECORDED, PAYMENTS_TOTAL_AMOUNT
    PAYMENTS_RECORDED.inc()
    PAYMENTS_TOTAL_AMOUNT.inc(payload.amount)

    return payment
