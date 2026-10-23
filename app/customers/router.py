from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.auth.deps import get_current_user, require_staff, require_admin_or_manager
from app.users.models import User
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ForbiddenError
from app.audit.service import record_audit
from app.customers.models import Customer, Property
from app.customers.schemas import (
    CustomerCreate, CustomerUpdate, CustomerOut, CustomerListItem, PropertyCreate, PropertyOut,
)
from app.common.pagination import Page, paginate, apply_sort

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _get_customer_or_404(db: Session, customer_id: str) -> Customer:
    customer = db.query(Customer).options(joinedload(Customer.properties)).filter(
        Customer.id == customer_id
    ).first()
    if not customer:
        raise NotFoundError("Customer", customer_id)
    return customer


def enforce_customer_access(customer_id: str, current_user: User):
    """The single choke point for customer data isolation: a CUSTOMER
    role may only ever access the customer record linked to their own
    user account. Staff roles may access any customer."""
    if current_user.role == UserRole.CUSTOMER and current_user.customer_id != customer_id:
        raise ForbiddenError("You do not have access to this customer's data")


@router.get("", response_model=Page[CustomerListItem])
def list_customers(
    q: str | None = Query(default=None, description="Search by name, company, email"),
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    query = db.query(Customer)
    if not include_archived:
        query = query.filter(Customer.is_archived.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Customer.contact_name.ilike(like))
            | (Customer.company_name.ilike(like))
            | (Customer.email.ilike(like))
        )
    query = apply_sort(query, Customer, sort_by, sort_dir)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/export/csv")
def export_customers_csv(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    customers = db.query(Customer).filter(Customer.is_archived.is_(False)).order_by(Customer.created_at.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Company", "Contact", "Email", "Phone", "Billing Address", "Created At"])
    for c in customers:
        writer.writerow([c.company_name or "", c.contact_name, c.email, c.phone, c.billing_address or "",
                          c.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=customers.csv"})


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(
    payload: CustomerCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)
):
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.flush()
    record_audit(db, current_user, "customer.created", "Customer", customer.id, new_state=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    enforce_customer_access(customer_id, current_user)
    return _get_customer_or_404(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: str, payload: CustomerUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    customer = _get_customer_or_404(db, customer_id)
    previous = {"contact_name": customer.contact_name, "email": customer.email, "phone": customer.phone}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    record_audit(db, current_user, "customer.updated", "Customer", customer.id, previous_state=previous,
                 new_state=payload.model_dump(exclude_unset=True, mode="json"))
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/{customer_id}/archive", response_model=CustomerOut)
def archive_customer(
    customer_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)
):
    from app.common.mixins import utcnow

    customer = _get_customer_or_404(db, customer_id)
    customer.is_archived = True
    customer.archived_at = utcnow()
    record_audit(db, current_user, "customer.archived", "Customer", customer.id)
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/{customer_id}/properties", response_model=PropertyOut, status_code=201)
def add_property(
    customer_id: str, payload: PropertyCreate, db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    _get_customer_or_404(db, customer_id)
    prop = Property(customer_id=customer_id, **payload.model_dump())
    db.add(prop)
    db.flush()
    record_audit(db, current_user, "property.created", "Property", prop.id, new_state=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(prop)
    return prop


@router.get("/{customer_id}/properties", response_model=list[PropertyOut])
def list_properties(customer_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    enforce_customer_access(customer_id, current_user)
    _get_customer_or_404(db, customer_id)
    return db.query(Property).filter(Property.customer_id == customer_id, Property.is_archived.is_(False)).all()
