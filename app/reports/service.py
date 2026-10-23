"""
Analytics, the owner dashboard, and the "Attention Required" operational
alert center. Kept in one service module since these are all
cross-domain aggregate queries rather than a single entity's business
logic.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.common.enums import JobStatus, InvoiceStatus, LeadStatus, QuoteStatus, ContractStatus
from app.jobs.models import Job, JobAssignment
from app.invoices.models import Invoice
from app.leads.models import Lead
from app.quotes.models import Quote
from app.contracts.models import Contract
from app.customers.models import Customer
from app.feedback.models import Feedback
from app.employees.models import Employee


def _range_bounds(range_key: str, custom_start=None, custom_end=None):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "today":
        return today_start, now
    if range_key == "this_week":
        return today_start - timedelta(days=today_start.weekday()), now
    if range_key == "this_month":
        return today_start.replace(day=1), now
    if range_key == "last_month":
        first_this_month = today_start.replace(day=1)
        last_month_end = first_this_month - timedelta(seconds=1)
        return last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0), first_this_month
    if range_key == "this_year":
        return today_start.replace(month=1, day=1), now
    if range_key == "custom" and custom_start and custom_end:
        return custom_start, custom_end
    return today_start - timedelta(days=30), now  # default: trailing 30 days


def dashboard_summary(db: Session) -> dict:
    """
    Rewritten to push every aggregation into SQL rather than loading
    full row sets into Python (the original version did `db.query(...).all()`
    then `sum()`'d in Python for revenue and outstanding balances --
    fine at a few dozen rows, a full-table scan liability once a real
    company has years of invoices). `func.sum`/`func.count` let the
    database use its indexes and never materialize rows we don't need.
    """
    from sqlalchemy import func

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_7_days = now + timedelta(days=7)

    monthly_revenue_total = db.query(func.coalesce(func.sum(Invoice.total), 0.0)).filter(
        Invoice.created_at >= month_start
    ).scalar()

    active_contracts = db.query(Contract).filter(Contract.status == ContractStatus.ACTIVE).count()
    upcoming_jobs = db.query(Job).filter(
        Job.scheduled_start >= now, Job.scheduled_start <= next_7_days,
        Job.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]),
    ).count()
    completed_jobs_this_month = db.query(Job).filter(
        Job.status == JobStatus.COMPLETED, Job.completed_at >= month_start
    ).count()

    outstanding_statuses = [InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE]
    outstanding_total = db.query(func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0.0)).filter(
        Invoice.status.in_(outstanding_statuses)
    ).scalar()
    overdue_count, overdue_total = db.query(
        func.count(Invoice.id), func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0.0)
    ).filter(Invoice.status == InvoiceStatus.OVERDUE).first()

    new_leads_this_month = db.query(Lead).filter(Lead.created_at >= month_start).count()

    quotes_sent = db.query(Quote).filter(Quote.status.in_([
        QuoteStatus.SENT, QuoteStatus.VIEWED, QuoteStatus.ACCEPTED, QuoteStatus.REJECTED, QuoteStatus.EXPIRED,
    ])).count()
    quotes_accepted = db.query(Quote).filter(Quote.status == QuoteStatus.ACCEPTED).count()
    conversion_rate = round((quotes_accepted / quotes_sent) * 100, 1) if quotes_sent else 0.0

    avg_rating = db.query(func.avg(Feedback.rating)).scalar()

    return {
        "monthly_revenue": round(monthly_revenue_total or 0.0, 2),
        "active_contracts": active_contracts,
        "upcoming_jobs_next_7_days": upcoming_jobs,
        "completed_jobs_this_month": completed_jobs_this_month,
        "outstanding_invoice_total": round(outstanding_total or 0.0, 2),
        "overdue_invoice_count": overdue_count or 0,
        "overdue_invoice_total": round(overdue_total or 0.0, 2),
        "new_leads_this_month": new_leads_this_month,
        "quote_conversion_rate_percent": conversion_rate,
        "average_rating": round(avg_rating, 2) if avg_rating is not None else None,
    }


def attention_required(db: Session) -> dict:
    """Surfaces operational problems, not just numbers."""
    now = datetime.utcnow()
    soon = now + timedelta(days=3)
    expiring_soon = now + timedelta(days=30)

    unassigned_jobs = (
        db.query(Job)
        .outerjoin(JobAssignment)
        .filter(Job.status == JobStatus.SCHEDULED, Job.scheduled_start <= soon, JobAssignment.id.is_(None))
        .all()
    )
    overdue_invoices = db.query(Invoice).filter(Invoice.status == InvoiceStatus.OVERDUE).all()
    quotes_expiring = db.query(Quote).filter(
        Quote.status.in_([QuoteStatus.SENT, QuoteStatus.VIEWED]), Quote.valid_until <= soon, Quote.valid_until >= now,
    ).all()
    contracts_expiring = db.query(Contract).filter(
        Contract.status == ContractStatus.ACTIVE, Contract.end_date.isnot(None),
        Contract.end_date <= expiring_soon, Contract.end_date >= now,
    ).all()
    jobs_missing_proof = [
        j for j in db.query(Job).filter(Job.status == JobStatus.COMPLETED).order_by(Job.completed_at.desc()).limit(50).all()
        if j.requires_photo_proof and {p.photo_type.value for p in j.photos} < {"BEFORE", "AFTER"}
    ]
    failed_jobs = db.query(Job).filter(Job.status.in_([JobStatus.NO_SHOW])).order_by(Job.scheduled_start.desc()).limit(20).all()
    low_ratings = db.query(Feedback).filter(Feedback.rating <= 2).order_by(Feedback.created_at.desc()).limit(10).all()

    def job_summary(j: Job):
        return {"id": j.id, "reference_number": j.reference_number, "scheduled_start": j.scheduled_start,
                "customer_name": j.customer.display_name if j.customer else None}

    return {
        "unassigned_jobs": [job_summary(j) for j in unassigned_jobs],
        "overdue_invoices": [{"id": i.id, "reference_number": i.reference_number, "balance_due": i.balance_due} for i in overdue_invoices],
        "quotes_expiring_soon": [{"id": q.id, "reference_number": q.reference_number, "valid_until": q.valid_until} for q in quotes_expiring],
        "contracts_expiring_soon": [{"id": c.id, "reference_number": c.reference_number, "end_date": c.end_date} for c in contracts_expiring],
        "jobs_missing_proof": [job_summary(j) for j in jobs_missing_proof],
        "no_show_jobs": [job_summary(j) for j in failed_jobs],
        "recent_low_ratings": [{"id": f.id, "rating": f.rating, "comment": f.comment} for f in low_ratings],
    }


def analytics(db: Session, range_key: str, custom_start=None, custom_end=None) -> dict:
    start, end = _range_bounds(range_key, custom_start, custom_end)

    invoices_in_range = db.query(Invoice).filter(Invoice.created_at >= start, Invoice.created_at <= end).all()
    jobs_in_range = db.query(Job).filter(Job.scheduled_start >= start, Job.scheduled_start <= end).all()
    completed = [j for j in jobs_in_range if j.status == JobStatus.COMPLETED]
    cancelled = [j for j in jobs_in_range if j.status in (JobStatus.CANCELLED, JobStatus.NO_SHOW)]
    leads_in_range = db.query(Lead).filter(Lead.created_at >= start, Lead.created_at <= end).all()
    quotes_in_range = db.query(Quote).filter(Quote.created_at >= start, Quote.created_at <= end).all()
    accepted_quotes = [q for q in quotes_in_range if q.status == QuoteStatus.ACCEPTED]
    contracts_in_range = db.query(Contract).filter(Contract.created_at >= start, Contract.created_at <= end).all()

    durations = [j.actual_duration_minutes for j in completed if j.actual_duration_minutes]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    ratings = [f.rating for j in completed if (f := j.feedback)]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    outstanding = db.query(Invoice).filter(
        Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE])
    ).all()

    workload = {}
    for emp in db.query(Employee).filter(Employee.is_active.is_(True)).all():
        count = (
            db.query(Job).join(JobAssignment)
            .filter(JobAssignment.employee_id == emp.id, Job.scheduled_start >= start, Job.scheduled_start <= end)
            .count()
        )
        workload[emp.full_name] = count

    return {
        "range": {"start": start, "end": end},
        "revenue": round(sum(i.total for i in invoices_in_range), 2),
        "jobs_scheduled": len(jobs_in_range),
        "jobs_completed": len(completed),
        "jobs_cancelled_or_no_show": len(cancelled),
        "new_leads": len(leads_in_range),
        "quotes_sent": len(quotes_in_range),
        "quotes_accepted": len(accepted_quotes),
        "quote_conversion_rate_percent": round((len(accepted_quotes) / len(quotes_in_range)) * 100, 1) if quotes_in_range else 0.0,
        "new_contracts": len(contracts_in_range),
        "average_job_duration_minutes": avg_duration,
        "average_rating": avg_rating,
        "outstanding_invoice_total": round(sum(i.balance_due for i in outstanding), 2),
        "employee_workload": workload,
    }


def revenue_trend(db: Session, months: int = 6) -> list[dict]:
    now = datetime.utcnow()
    result = []
    for i in range(months - 1, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        total = sum(
            inv.total for inv in db.query(Invoice).filter(Invoice.created_at >= start, Invoice.created_at < end).all()
        )
        result.append({"month": start.strftime("%b %Y"), "revenue": round(total, 2)})
    return result


def customer_growth(db: Session, months: int = 6) -> list[dict]:
    now = datetime.utcnow()
    result = []
    for i in range(months - 1, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        end = datetime(year, month + 1, 1) if month != 12 else datetime(year + 1, 1, 1)
        count = db.query(Customer).filter(Customer.created_at < end).count()
        result.append({"month": datetime(year, month, 1).strftime("%b %Y"), "total_customers": count})
    return result


def _month_bounds(now: datetime, i: int):
    year = now.year
    month = now.month - i
    while month <= 0:
        month += 12
        year -= 1
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def jobs_completed_trend(db: Session, months: int = 6) -> list[dict]:
    now = datetime.utcnow()
    result = []
    for i in range(months - 1, -1, -1):
        start, end = _month_bounds(now, i)
        completed = db.query(Job).filter(Job.status == JobStatus.COMPLETED, Job.completed_at >= start,
                                          Job.completed_at < end).count()
        cancelled = db.query(Job).filter(Job.status.in_([JobStatus.CANCELLED, JobStatus.NO_SHOW]),
                                          Job.scheduled_start >= start, Job.scheduled_start < end).count()
        result.append({"month": start.strftime("%b %Y"), "completed": completed, "cancelled_or_no_show": cancelled})
    return result


def lead_conversion_trend(db: Session, months: int = 6) -> list[dict]:
    now = datetime.utcnow()
    result = []
    for i in range(months - 1, -1, -1):
        start, end = _month_bounds(now, i)
        new_leads = db.query(Lead).filter(Lead.created_at >= start, Lead.created_at < end).count()
        won = db.query(Lead).filter(Lead.status == LeadStatus.WON, Lead.created_at >= start, Lead.created_at < end).count()
        result.append({"month": start.strftime("%b %Y"), "new_leads": new_leads, "won": won})
    return result


def contract_status_breakdown(db: Session) -> list[dict]:
    result = []
    for status in ContractStatus:
        count = db.query(Contract).filter(Contract.status == status).count()
        result.append({"status": status.value, "count": count})
    return result


def customer_timeline(db: Session, customer_id: str) -> list[dict]:
    """The Customer Service Timeline: every major milestone for one
    customer, in chronological order -- Lead -> Quote -> Contract -> Job
    -> Invoice -> Payment -> Feedback -- so staff (or the customer
    themself) can see the whole relationship at a glance."""
    from app.leads.models import Lead as LeadModel
    from app.invoices.models import Invoice as InvoiceModel
    from app.payments.models import Payment as PaymentModel
    from app.feedback.models import Feedback as FeedbackModel

    events = []

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return []

    lead = db.query(LeadModel).filter(LeadModel.converted_customer_id == customer_id).first()
    if lead:
        events.append({"type": "Lead", "label": f"Lead {lead.reference_number} created", "at": lead.created_at,
                       "entity_id": lead.id})

    quotes = db.query(Quote).filter(Quote.customer_id == customer_id).all()
    for q in quotes:
        events.append({"type": "Quote", "label": f"Quote {q.reference_number} — {q.status.value}",
                       "at": q.created_at, "entity_id": q.id})
        if q.responded_at:
            events.append({"type": "Quote", "label": f"Quote {q.reference_number} {q.status.value.lower()}",
                           "at": q.responded_at, "entity_id": q.id})

    contracts = db.query(Contract).filter(Contract.customer_id == customer_id).all()
    for c in contracts:
        events.append({"type": "Contract", "label": f"Contract {c.reference_number} started ({c.frequency.value})",
                       "at": c.created_at, "entity_id": c.id})
        if c.cancelled_at:
            events.append({"type": "Contract", "label": f"Contract {c.reference_number} cancelled",
                           "at": c.cancelled_at, "entity_id": c.id})

    jobs = db.query(Job).filter(Job.customer_id == customer_id, Job.status == JobStatus.COMPLETED).all()
    for j in jobs:
        events.append({"type": "Job", "label": f"Job {j.reference_number} completed", "at": j.completed_at,
                       "entity_id": j.id})

    invoices = db.query(InvoiceModel).filter(InvoiceModel.customer_id == customer_id).all()
    for inv in invoices:
        events.append({"type": "Invoice", "label": f"Invoice {inv.reference_number} — {inv.status.value}",
                       "at": inv.created_at, "entity_id": inv.id})
        for p in inv.payments:
            events.append({"type": "Payment", "label": f"Payment of ${p.amount:,.2f} received",
                           "at": p.paid_at, "entity_id": p.id})

    feedbacks = db.query(FeedbackModel).filter(FeedbackModel.customer_id == customer_id).all()
    for f in feedbacks:
        events.append({"type": "Feedback", "label": f"Feedback submitted — {f.rating}★", "at": f.created_at,
                       "entity_id": f.id})

    events = [e for e in events if e["at"] is not None]
    events.sort(key=lambda e: e["at"])
    return events


def global_search(db: Session, q: str, current_role: str, current_customer_id: str | None) -> list[dict]:
    """
    Staff search goes through the FTS5 index (see app/search/index.py)
    for genuine scalable full-text search. Customer search deliberately
    bypasses it: a customer's own record set is tiny (their own
    profile, their own invoices) and scoping FTS results by customer_id
    would need a WHERE clause the shared index doesn't carry per-row --
    simpler and just as fast to query those few rows directly.
    """
    if current_role == "CUSTOMER":
        like = f"%{q}%"
        results = []
        for c in db.query(Customer).filter(Customer.id == current_customer_id).all():
            results.append({"type": "Customer", "id": c.id, "label": c.display_name})
        for inv in db.query(Invoice).filter(Invoice.customer_id == current_customer_id,
                                             Invoice.reference_number.ilike(like)).all():
            results.append({"type": "Invoice", "id": inv.id, "label": inv.reference_number})
        return results

    from app.search.index import search_fts
    results = search_fts(db, q, limit=30)
    if current_role == "EMPLOYEE":
        results = [r for r in results if r["type"] != "Employee"]
    return results
