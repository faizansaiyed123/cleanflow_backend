"""
Materialized daily metrics rollup.

The problem this solves: `dashboard_summary()` and the trend endpoints
originally computed their numbers by loading every Invoice/Job row that
matched a date filter into Python and summing them there. That's fine
at demo scale (dozens of rows) and actively dangerous at production
scale -- a company with 3 years of daily jobs across hundreds of
customers would mean the dashboard does a full-table aggregation, in
Python, on every single page load.

The fix used by essentially every real analytics dashboard: precompute
a small, indexed summary table (one row per day) on a schedule (here,
the background worker every 30s; in production this would run nightly
plus a cheap "today" refresh), and have dashboard reads sum a handful
of pre-aggregated day-rows instead of scanning the full transactional
tables. This is the same idea as a materialized view, implemented by
hand since SQLite doesn't support real materialized views.
"""
from datetime import datetime, timedelta

from sqlalchemy import Column, String, Float, Integer, func
from sqlalchemy.orm import Session

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import JobStatus, LeadStatus
from app.invoices.models import Invoice
from app.jobs.models import Job
from app.leads.models import Lead
from app.customers.models import Customer
from app.feedback.models import Feedback


class DailyMetric(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "daily_metrics"

    metric_date = Column(String(10), unique=True, nullable=False, index=True)  # "YYYY-MM-DD"
    revenue = Column(Float, nullable=False, default=0.0)
    jobs_completed = Column(Integer, nullable=False, default=0)
    jobs_cancelled_or_no_show = Column(Integer, nullable=False, default=0)
    new_leads = Column(Integer, nullable=False, default=0)
    new_customers = Column(Integer, nullable=False, default=0)
    average_rating = Column(Float, nullable=True)


def _recompute_for_date(db: Session, day: datetime) -> None:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    key = start.strftime("%Y-%m-%d")

    revenue = db.query(func.coalesce(func.sum(Invoice.total), 0.0)).filter(
        Invoice.created_at >= start, Invoice.created_at < end
    ).scalar()
    completed = db.query(func.count(Job.id)).filter(
        Job.status == JobStatus.COMPLETED, Job.completed_at >= start, Job.completed_at < end
    ).scalar()
    cancelled = db.query(func.count(Job.id)).filter(
        Job.status.in_([JobStatus.CANCELLED, JobStatus.NO_SHOW]),
        Job.scheduled_start >= start, Job.scheduled_start < end,
    ).scalar()
    new_leads = db.query(func.count(Lead.id)).filter(Lead.created_at >= start, Lead.created_at < end).scalar()
    new_customers = db.query(func.count(Customer.id)).filter(
        Customer.created_at >= start, Customer.created_at < end
    ).scalar()
    avg_rating = db.query(func.avg(Feedback.rating)).filter(
        Feedback.created_at >= start, Feedback.created_at < end
    ).scalar()

    row = db.query(DailyMetric).filter(DailyMetric.metric_date == key).first()
    if not row:
        row = DailyMetric(metric_date=key)
        db.add(row)
    row.revenue = round(revenue or 0.0, 2)
    row.jobs_completed = completed or 0
    row.jobs_cancelled_or_no_show = cancelled or 0
    row.new_leads = new_leads or 0
    row.new_customers = new_customers or 0
    row.average_rating = round(avg_rating, 2) if avg_rating is not None else None


def recompute_daily_metrics(db: Session, days_back: int = 3) -> None:
    """Recompute the last `days_back` days (today plus a couple days of
    slack for anything backdated/corrected) rather than the whole
    history every tick -- historical days don't change, so there's no
    need to redo them once they're settled."""
    now = datetime.utcnow()
    for i in range(days_back):
        _recompute_for_date(db, now - timedelta(days=i))


def get_metrics_range(db: Session, start: datetime, end: datetime) -> list[DailyMetric]:
    return (
        db.query(DailyMetric)
        .filter(DailyMetric.metric_date >= start.strftime("%Y-%m-%d"), DailyMetric.metric_date < end.strftime("%Y-%m-%d"))
        .order_by(DailyMetric.metric_date)
        .all()
    )
