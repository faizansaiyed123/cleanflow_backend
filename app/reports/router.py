from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_admin_or_manager, get_current_user
from app.users.models import User
from app.reports import service as reports_service

router = APIRouter(tags=["reports"])


@router.get("/api/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    from app.invoices.service import refresh_overdue_status
    from app.quotes.service import expire_stale_quotes
    refresh_overdue_status(db)
    expire_stale_quotes(db)
    db.commit()
    return reports_service.dashboard_summary(db)


@router.get("/api/dashboard/attention-required")
def get_attention_required(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    from app.invoices.service import refresh_overdue_status
    from app.quotes.service import expire_stale_quotes
    refresh_overdue_status(db)
    expire_stale_quotes(db)
    db.commit()
    return reports_service.attention_required(db)


@router.get("/api/dashboard/revenue-trend")
def get_revenue_trend(months: int = 6, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    return reports_service.revenue_trend(db, months)


@router.get("/api/dashboard/customer-growth")
def get_customer_growth(months: int = 6, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    return reports_service.customer_growth(db, months)


@router.get("/api/dashboard/jobs-trend")
def get_jobs_trend(months: int = 6, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    return reports_service.jobs_completed_trend(db, months)


@router.get("/api/dashboard/lead-conversion-trend")
def get_lead_conversion_trend(months: int = 6, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    return reports_service.lead_conversion_trend(db, months)


@router.get("/api/dashboard/contract-status-breakdown")
def get_contract_status_breakdown(db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    return reports_service.contract_status_breakdown(db)


@router.get("/api/analytics")
def get_analytics(
    range: str = Query(default="this_month", description="today|this_week|this_month|last_month|this_year|custom"),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    return reports_service.analytics(db, range, start, end)


@router.get("/api/search")
def search(q: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if len(q.strip()) < 2:
        return []
    return reports_service.global_search(db, q.strip(), current_user.role.value, current_user.customer_id)


@router.get("/api/customers/{customer_id}/timeline")
def get_customer_timeline(customer_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.common.enums import UserRole
    from app.common.exceptions import ForbiddenError
    if current_user.role == UserRole.CUSTOMER and current_user.customer_id != customer_id:
        raise ForbiddenError("You do not have access to this customer's timeline")
    if current_user.role == UserRole.EMPLOYEE:
        raise ForbiddenError("Employees do not have access to customer timelines")
    return reports_service.customer_timeline(db, customer_id)


@router.get("/api/customer-portal/dashboard")
def customer_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.common.enums import UserRole, ContractStatus, JobStatus, InvoiceStatus
    from app.common.exceptions import ForbiddenError
    from app.contracts.models import Contract
    from app.jobs.models import Job
    from app.invoices.models import Invoice
    from app.feedback.models import Feedback
    from datetime import datetime as dt, timezone

    if current_user.role != UserRole.CUSTOMER:
        raise ForbiddenError("This view is for customers")
    cid = current_user.customer_id
    now = dt.utcnow()

    active_contracts = db.query(Contract).filter(Contract.customer_id == cid, Contract.status == ContractStatus.ACTIVE).count()
    upcoming_jobs = (
        db.query(Job).filter(Job.customer_id == cid, Job.scheduled_start >= now,
                              Job.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]))
        .order_by(Job.scheduled_start).limit(5).all()
    )
    recent_completed = (
        db.query(Job).filter(Job.customer_id == cid, Job.status == JobStatus.COMPLETED)
        .order_by(Job.completed_at.desc()).limit(5).all()
    )
    outstanding_invoices = db.query(Invoice).filter(
        Invoice.customer_id == cid, Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE])
    ).all()
    ratings = [f.rating for f in db.query(Feedback).filter(Feedback.customer_id == cid).all()]

    return {
        "active_contracts": active_contracts,
        "upcoming_jobs": [{"id": j.id, "reference_number": j.reference_number, "scheduled_start": j.scheduled_start,
                            "status": j.status} for j in upcoming_jobs],
        "recent_service_reports": [{"id": j.id, "reference_number": j.reference_number, "completed_at": j.completed_at}
                                    for j in recent_completed],
        "outstanding_invoice_total": round(sum(i.balance_due for i in outstanding_invoices), 2),
        "outstanding_invoice_count": len(outstanding_invoices),
        "average_rating_given": round(sum(ratings) / len(ratings), 2) if ratings else None,
    }
