"""
Business logic for the quote lifecycle: creation (via the pricing
engine), sending, viewing, and -- most importantly -- acceptance, which
transactionally provisions the customer's Customer/Property/Contract/
RecurringSchedule records and kicks off job generation. See
`accept_quote` for the transactional/idempotency guarantees.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.common.enums import QuoteStatus, ContractStatus, UserRole
from app.common.exceptions import ConflictError, ValidationAppError, NotFoundError
from app.common.reference_numbers import next_reference
from app.audit.service import record_audit
from app.pricing.engine import calculate_quote_price, QuoteCalculationInput
from app.quotes.models import Quote, QuoteItem
from app.leads.models import Lead
from app.customers.models import Customer, Property
from app.services.models import Service
from app.users.models import User
from app.auth.security import hash_password
from app.notifications.service import notify_user, notify_role
from app.events.bus import publish, EventType


def _ensure_customer_for_quote(db: Session, lead: Lead | None, customer_id: str | None) -> Customer:
    if customer_id:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise NotFoundError("Customer", customer_id)
        return customer

    if not lead:
        raise ValidationAppError("A quote must reference either a lead_id or a customer_id")

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
    lead.converted_customer_id = customer.id

    # Provision a customer-portal login so they can view/accept the quote.
    # Demo simplification: a known temporary password is returned to staff
    # to relay to the customer, standing in for a real "set your password"
    # email invite flow.
    if not customer.email or db.query(User).filter(User.email == customer.email.lower()).first():
        pass
    else:
        portal_user = User(
            email=customer.email.lower(),
            hashed_password=hash_password("Welcome123!"),
            full_name=customer.contact_name,
            role=UserRole.CUSTOMER,
            customer_id=customer.id,
        )
        db.add(portal_user)

    return customer


def _ensure_property_for_quote(db: Session, customer: Customer, quote_payload, property_id: str | None) -> Property:
    if property_id:
        prop = db.query(Property).filter(Property.id == property_id, Property.customer_id == customer.id).first()
        if not prop:
            raise NotFoundError("Property", property_id)
        return prop

    # Look for a matching existing property before creating a new one, to
    # avoid duplicate property records when a customer requests multiple
    # quotes for the same site.
    existing = (
        db.query(Property)
        .filter(Property.customer_id == customer.id, Property.is_archived.is_(False))
        .first()
    )
    if existing:
        return existing

    prop = Property(
        customer_id=customer.id,
        label="Primary Location",
        address_line1=customer.billing_address or "TBD",
        city="", state="", zip_code="",
        property_type=quote_payload.property_type,
        square_footage=quote_payload.square_footage,
        bathrooms=quote_payload.bathrooms,
        floors=quote_payload.floors,
    )
    db.add(prop)
    db.flush()
    return prop


def create_quote(db: Session, payload, created_by: User) -> Quote:
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first() if payload.lead_id else None
    if payload.lead_id and not lead:
        raise NotFoundError("Lead", payload.lead_id)

    customer = _ensure_customer_for_quote(db, lead, payload.customer_id)
    prop = _ensure_property_for_quote(db, customer, payload, payload.property_id)

    primary_service = db.query(Service).filter(Service.id == payload.primary_service_id).first()
    if not primary_service:
        raise NotFoundError("Service", payload.primary_service_id)

    calc_input = QuoteCalculationInput(
        property_type=payload.property_type,
        square_footage=payload.square_footage,
        bathrooms=payload.bathrooms,
        floors=payload.floors,
        frequency=payload.frequency,
        addon_service_ids=payload.addon_service_ids,
        has_special_conditions=payload.has_special_conditions,
        manual_discount_percent=payload.manual_discount_percent,
        manual_discount_reason=payload.manual_discount_reason,
    )
    result = calculate_quote_price(db, calc_input)
    breakdown = result.as_dict()

    valid_days = payload.valid_for_days or 14
    reference = next_reference(db, "quote")

    quote = Quote(
        reference_number=reference,
        lead_id=lead.id if lead else None,
        customer_id=customer.id,
        property_id=prop.id,
        property_type=payload.property_type,
        square_footage=payload.square_footage,
        bathrooms=payload.bathrooms,
        floors=payload.floors,
        frequency=payload.frequency,
        has_special_conditions=str(payload.has_special_conditions).lower(),
        addon_service_ids=payload.addon_service_ids,
        manual_discount_percent=payload.manual_discount_percent,
        manual_discount_reason=payload.manual_discount_reason,
        pricing_breakdown=breakdown,
        subtotal=result.subtotal,
        tax_amount=0.0,
        total=result.total,
        status=QuoteStatus.DRAFT,
        valid_until=datetime.utcnow() + timedelta(days=valid_days),
        terms=payload.terms,
        notes=payload.notes,
        created_by_user_id=created_by.id,
    )
    db.add(quote)
    db.flush()

    db.add(QuoteItem(quote_id=quote.id, service_id=primary_service.id, description=primary_service.name,
                      is_addon="false", amount=next(i["amount"] for i in breakdown["line_items"] if i["label"] == "Base service")))
    if payload.addon_service_ids:
        addons = db.query(Service).filter(Service.id.in_(payload.addon_service_ids)).all()
        for addon in addons:
            db.add(QuoteItem(quote_id=quote.id, service_id=addon.id, description=addon.name,
                              is_addon="true", amount=addon.base_rate))

    if lead:
        lead.status = lead.status if lead.status.value in ("WON", "LOST") else lead.status.__class__("QUOTED")

    record_audit(db, created_by, "quote.created", "Quote", quote.id, new_state={"total": result.total})
    return quote


def send_quote(db: Session, quote: Quote, actor: User) -> Quote:
    if quote.status not in (QuoteStatus.DRAFT,):
        raise ConflictError(f"Only draft quotes can be sent (current status: {quote.status.value})")
    quote.status = QuoteStatus.SENT
    quote.sent_at = datetime.utcnow()
    if quote.customer_id:
        customer = db.query(Customer).filter(Customer.id == quote.customer_id).first()
        if customer and customer.user:
            publish(db, EventType.QUOTE_SENT, {
                "quote_id": quote.id, "reference_number": quote.reference_number, "total": quote.total,
                "customer_user_id": customer.user.id,
            })
    record_audit(db, actor, "quote.sent", "Quote", quote.id)
    return quote


def mark_viewed(db: Session, quote: Quote) -> Quote:
    if quote.status == QuoteStatus.SENT:
        quote.status = QuoteStatus.VIEWED
        quote.viewed_at = datetime.utcnow()
    return quote


def expire_stale_quotes(db: Session) -> int:
    """Run periodically (or lazily on read) to flip SENT/VIEWED quotes past
    their valid_until date to EXPIRED."""
    now = datetime.utcnow()
    stale = (
        db.query(Quote)
        .filter(Quote.status.in_([QuoteStatus.SENT, QuoteStatus.VIEWED]), Quote.valid_until < now)
        .all()
    )
    for q in stale:
        q.status = QuoteStatus.EXPIRED
    return len(stale)


def clone_quote(db: Session, original: Quote, actor: User) -> Quote:
    reference = next_reference(db, "quote")
    clone = Quote(
        reference_number=reference,
        lead_id=original.lead_id,
        customer_id=original.customer_id,
        property_id=original.property_id,
        property_type=original.property_type,
        square_footage=original.square_footage,
        bathrooms=original.bathrooms,
        floors=original.floors,
        frequency=original.frequency,
        has_special_conditions=original.has_special_conditions,
        addon_service_ids=original.addon_service_ids,
        manual_discount_percent=original.manual_discount_percent,
        manual_discount_reason=original.manual_discount_reason,
        pricing_breakdown=original.pricing_breakdown,
        subtotal=original.subtotal,
        tax_amount=original.tax_amount,
        total=original.total,
        status=QuoteStatus.DRAFT,
        valid_until=datetime.utcnow() + timedelta(days=14),
        terms=original.terms,
        notes=original.notes,
        created_by_user_id=actor.id,
        cloned_from_quote_id=original.id,
    )
    db.add(clone)
    record_audit(db, actor, "quote.cloned", "Quote", clone.id, previous_state={"cloned_from": original.id})
    return clone
