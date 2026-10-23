from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_staff, require_admin_or_manager, get_current_user
from app.users.models import User
from app.common.enums import LeadStatus, LeadSource
from app.common.exceptions import NotFoundError, ConflictError
from app.common.reference_numbers import next_reference
from app.audit.service import record_audit
from app.leads.models import Lead
from app.leads.schemas import (
    PublicQuoteRequest, PublicQuoteRequestResponse, LeadUpdate, LeadOut, LeadConvertRequest,
)
from app.common.pagination import Page, paginate, apply_sort
from app.customers.models import Customer, Property
from app.customers.schemas import CustomerOut
from app.notifications.service import notify_role
from app.events.bus import publish, EventType
from app.observability.rate_limit_deps import rate_limited
from app.observability.rate_limit import public_quote_limiter

router = APIRouter(tags=["leads"])


@router.post("/api/public/quote-requests", response_model=PublicQuoteRequestResponse, status_code=201,
             dependencies=[Depends(rate_limited(public_quote_limiter, "public_quote_request"))])
def submit_public_quote_request(payload: PublicQuoteRequest, db: Session = Depends(get_db)):
    """Public, unauthenticated endpoint used by the marketing site's
    'Request a Quote' form. Always creates a Lead so nothing submitted
    by a prospective customer is ever lost."""
    reference = next_reference(db, "lead")
    lead = Lead(
        reference_number=reference,
        contact_name=payload.contact_name,
        company_name=payload.company_name,
        email=payload.email,
        phone=payload.phone,
        address_line1=payload.address_line1,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        property_type=payload.property_type,
        square_footage=payload.square_footage,
        bathrooms=payload.bathrooms,
        floors=payload.floors,
        frequency=payload.frequency,
        requested_services=payload.requested_services,
        requested_addons=payload.requested_addons,
        preferred_start_date=payload.preferred_start_date,
        preferred_time=payload.preferred_time,
        notes=payload.notes,
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
    )
    db.add(lead)
    db.flush()
    record_audit(db, None, "lead.created", "Lead", lead.id, new_state={"reference_number": reference, "source": "WEBSITE"})
    publish(db, EventType.LEAD_CREATED, {
        "lead_id": lead.id, "reference_number": reference, "contact_name": payload.contact_name,
    })
    db.commit()
    return PublicQuoteRequestResponse(reference_number=reference)


@router.get("/api/leads", response_model=Page[LeadOut])
def list_leads(
    status: LeadStatus | None = None,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    query = db.query(Lead)
    if status:
        query = query.filter(Lead.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter((Lead.contact_name.ilike(like)) | (Lead.company_name.ilike(like)) | (Lead.email.ilike(like)))
    query = apply_sort(query, Lead, sort_by, sort_dir)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/api/leads/export/csv")
def export_leads_csv(db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Reference", "Contact", "Company", "Email", "Phone", "Source", "Status", "Estimated Value", "Created At"])
    for l in leads:
        writer.writerow([l.reference_number, l.contact_name, l.company_name or "", l.email, l.phone,
                          l.source.value, l.status.value, l.estimated_value or "", l.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.get("/api/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise NotFoundError("Lead", lead_id)
    return lead


@router.patch("/api/leads/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: str, payload: LeadUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_staff)
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise NotFoundError("Lead", lead_id)
    changes = payload.model_dump(exclude_unset=True)
    previous = {"status": lead.status.value}
    for field, value in changes.items():
        setattr(lead, field, value)
    record_audit(db, current_user, "lead.updated", "Lead", lead.id, previous_state=previous,
                 new_state={k: (v.value if hasattr(v, "value") else str(v)) for k, v in changes.items()})
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/api/leads/{lead_id}/convert", response_model=CustomerOut)
def convert_lead_to_customer(
    lead_id: str, payload: LeadConvertRequest, db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Turn a qualified lead into a real Customer record. Idempotent:
    calling this twice on the same lead returns the existing customer
    rather than creating a duplicate."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise NotFoundError("Lead", lead_id)

    if lead.converted_customer_id:
        existing = db.query(Customer).filter(Customer.id == lead.converted_customer_id).first()
        if existing:
            return existing

    customer = Customer(
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        email=lead.email,
        phone=lead.phone,
        billing_address=", ".join(filter(None, [lead.address_line1, lead.city, lead.state, lead.zip_code])) or None,
    )
    db.add(customer)
    db.flush()

    if payload.create_property and lead.address_line1 and lead.square_footage:
        db.add(Property(
            customer_id=customer.id,
            label="Primary Location",
            address_line1=lead.address_line1,
            city=lead.city or "",
            state=lead.state or "",
            zip_code=lead.zip_code or "",
            property_type=lead.property_type,
            square_footage=lead.square_footage,
            bathrooms=lead.bathrooms or 1,
            floors=lead.floors or 1,
        ))

    lead.converted_customer_id = customer.id
    if lead.status not in (LeadStatus.WON,):
        lead.status = LeadStatus.QUALIFIED if lead.status == LeadStatus.NEW else lead.status

    record_audit(db, current_user, "lead.converted", "Lead", lead.id, new_state={"customer_id": customer.id})
    db.commit()
    db.refresh(customer)
    return customer
