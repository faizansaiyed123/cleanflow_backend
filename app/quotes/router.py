from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import get_current_user, require_staff, require_admin_or_manager
from app.users.models import User
from app.common.enums import UserRole, QuoteStatus
from app.common.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.audit.service import record_audit
from app.quotes.models import Quote
from app.quotes.schemas import QuoteCreate, QuoteOut, QuoteRejectRequest
from app.quotes import service as quote_service
from app.contracts.service import activate_contract_from_accepted_quote
from app.contracts.schemas import ContractOut
from app.notifications.service import notify_role
from app.events.bus import publish, EventType
from app.common.pagination import Page, paginate, apply_sort

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


def _get_quote_or_404(db: Session, quote_id: str) -> Quote:
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not quote:
        raise NotFoundError("Quote", quote_id)
    return quote


def _enforce_quote_access(quote: Quote, current_user: User):
    if current_user.role == UserRole.CUSTOMER and quote.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this quote")


@router.get("", response_model=Page[QuoteOut])
def list_quotes(
    status: QuoteStatus | None = None,
    customer_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Quote)
    quote_service.expire_stale_quotes(db)
    db.commit()
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Quote.customer_id == current_user.customer_id)
    elif customer_id:
        query = query.filter(Quote.customer_id == customer_id)
    if status:
        query = query.filter(Quote.status == status)
    query = apply_sort(query, Quote, sort_by, sort_dir)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=QuoteOut, status_code=201)
def create_quote(payload: QuoteCreate, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    quote = quote_service.create_quote(db, payload, current_user)
    db.commit()
    db.refresh(quote)
    return quote


@router.get("/{quote_id}", response_model=QuoteOut)
def get_quote(quote_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = _get_quote_or_404(db, quote_id)
    _enforce_quote_access(quote, current_user)
    if current_user.role == UserRole.CUSTOMER:
        quote_service.mark_viewed(db, quote)
        db.commit()
        db.refresh(quote)
    return quote


@router.get("/{quote_id}/pdf")
def download_quote_pdf(quote_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.pdf_export.service import generate_quote_pdf
    from app.customers.models import Customer, Property
    from app.config.models import CompanySetting

    quote = _get_quote_or_404(db, quote_id)
    _enforce_quote_access(quote, current_user)

    customer = db.query(Customer).filter(Customer.id == quote.customer_id).first() if quote.customer_id else None
    property_ = db.query(Property).filter(Property.id == quote.property_id).first() if quote.property_id else None
    company = db.query(CompanySetting).first()

    pdf_bytes = generate_quote_pdf(quote, customer, property_, company)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{quote.reference_number}.pdf"'
    })


@router.post("/{quote_id}/clone", response_model=QuoteOut, status_code=201)
def clone_quote(quote_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    original = _get_quote_or_404(db, quote_id)
    clone = quote_service.clone_quote(db, original, current_user)
    db.commit()
    db.refresh(clone)
    return clone


@router.post("/{quote_id}/send", response_model=QuoteOut)
def send_quote(quote_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    quote = _get_quote_or_404(db, quote_id)
    quote_service.send_quote(db, quote, current_user)
    db.commit()
    db.refresh(quote)
    return quote


@router.post("/{quote_id}/accept", response_model=ContractOut)
def accept_quote(quote_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Customer (or staff on the customer's behalf) accepts a quote. This
    is the single trigger for the quote -> contract -> schedule -> jobs
    automation, executed as one DB transaction."""
    quote = _get_quote_or_404(db, quote_id)
    _enforce_quote_access(quote, current_user)

    if quote.status == QuoteStatus.ACCEPTED and quote.contract:
        return quote.contract

    if quote.status not in (QuoteStatus.SENT, QuoteStatus.VIEWED):
        raise ConflictError(f"Quote cannot be accepted from status {quote.status.value}")
    if quote.valid_until < datetime.utcnow():
        quote.status = QuoteStatus.EXPIRED
        db.commit()
        raise ConflictError("This quote has expired and can no longer be accepted")

    quote.status = QuoteStatus.ACCEPTED
    quote.responded_at = datetime.utcnow()
    record_audit(db, current_user, "quote.accepted", "Quote", quote.id)

    contract = activate_contract_from_accepted_quote(db, quote, current_user)
    publish(db, EventType.QUOTE_ACCEPTED, {
        "quote_id": quote.id, "reference_number": quote.reference_number, "contract_id": contract.id,
    })
    db.commit()
    db.refresh(contract)
    return contract


@router.post("/{quote_id}/reject", response_model=QuoteOut)
def reject_quote(quote_id: str, payload: QuoteRejectRequest, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    quote = _get_quote_or_404(db, quote_id)
    _enforce_quote_access(quote, current_user)
    if quote.status not in (QuoteStatus.SENT, QuoteStatus.VIEWED):
        raise ConflictError(f"Quote cannot be rejected from status {quote.status.value}")
    quote.status = QuoteStatus.REJECTED
    quote.responded_at = datetime.utcnow()
    record_audit(db, current_user, "quote.rejected", "Quote", quote.id, new_state={"reason": payload.reason})
    publish(db, EventType.QUOTE_REJECTED, {
        "quote_id": quote.id, "reference_number": quote.reference_number, "reason": payload.reason,
    })
    db.commit()
    db.refresh(quote)
    return quote
