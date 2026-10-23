from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import get_current_user, require_financial_access
from app.users.models import User
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ForbiddenError
from app.invoices.models import Invoice
from app.payments.models import Payment
from app.payments.schemas import PaymentCreate, PaymentOut
from app.payments import service as payment_service
from app.idempotency.service import idempotency_context, IdempotencyContext
from fastapi.encoders import jsonable_encoder

router = APIRouter(tags=["payments"])


@router.post("/api/invoices/{invoice_id}/payments", response_model=PaymentOut, status_code=201)
def record_payment(invoice_id: str, payload: PaymentCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_financial_access),
                    idem: IdempotencyContext = Depends(idempotency_context("payments.record"))):
    """
    Idempotency-Key protected: recording a payment is NOT naturally
    idempotent the way accepting a quote is -- POSTing the same $200
    payment twice (e.g. because a manager's browser retried a request
    that actually succeeded but the response was lost to a flaky
    network) would double the invoice's amount_paid and could silently
    misstate the customer's balance. A client that sends the same
    Idempotency-Key on retry gets the original response back instead of
    a second Payment row.
    """
    if idem.cached_response:
        return idem.cached_response

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise NotFoundError("Invoice", invoice_id)
    payment = payment_service.record_payment(db, invoice, payload, current_user)
    db.flush()
    response_body = jsonable_encoder(PaymentOut.model_validate(payment))
    idem.store(201, response_body)
    db.commit()
    return response_body


@router.get("/api/invoices/{invoice_id}/payments", response_model=list[PaymentOut])
def list_payments_for_invoice(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise NotFoundError("Invoice", invoice_id)
    if current_user.role == UserRole.CUSTOMER and invoice.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this invoice")
    if current_user.role == UserRole.EMPLOYEE:
        raise ForbiddenError("Employees do not have access to financial data")
    return db.query(Payment).filter(Payment.invoice_id == invoice_id).order_by(Payment.paid_at.desc()).all()


@router.get("/api/payments", response_model=list[PaymentOut])
def list_all_payments(db: Session = Depends(get_db), current_user: User = Depends(require_financial_access)):
    return db.query(Payment).order_by(Payment.paid_at.desc()).limit(200).all()
