from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_admin_or_manager, get_current_user
from app.users.models import User
from app.common.exceptions import NotFoundError, ValidationAppError, ConflictError
from app.audit.service import record_audit
from app.scheduling.models import RecurringSchedule, ScheduleException
from app.scheduling.schemas import (
    RecurringScheduleOut, RecurringScheduleUpdate, ScheduleExceptionCreate, ScheduleExceptionOut,
)
from app.scheduling.generator import generate_jobs_for_schedule
from app.jobs.models import Job
from app.common.enums import JobStatus

router = APIRouter(prefix="/api/scheduling", tags=["scheduling"])


@router.get("/contracts/{contract_id}/schedule", response_model=RecurringScheduleOut)
def get_schedule(contract_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    schedule = db.query(RecurringSchedule).filter(RecurringSchedule.contract_id == contract_id).first()
    if not schedule:
        raise NotFoundError("RecurringSchedule for contract", contract_id)
    return schedule


@router.patch("/schedules/{schedule_id}", response_model=RecurringScheduleOut)
def update_schedule(schedule_id: str, payload: RecurringScheduleUpdate, db: Session = Depends(get_db),
                     current_user: User = Depends(require_admin_or_manager)):
    """Editing the master pattern only affects occurrences generated
    AFTER this change (i.e. future dates beyond last_generated_through
    that haven't been turned into Job rows yet). Jobs already created
    are untouched -- reschedule/cancel those individually instead."""
    schedule = db.query(RecurringSchedule).filter(RecurringSchedule.id == schedule_id).first()
    if not schedule:
        raise NotFoundError("RecurringSchedule", schedule_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(schedule, field, value)
    record_audit(db, current_user, "schedule.updated", "RecurringSchedule", schedule.id, new_state=changes)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.post("/schedules/{schedule_id}/generate")
def regenerate_jobs(schedule_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    """Manually trigger catch-up generation (normally this would also run
    on a daily background job)."""
    schedule = db.query(RecurringSchedule).filter(RecurringSchedule.id == schedule_id).first()
    if not schedule:
        raise NotFoundError("RecurringSchedule", schedule_id)
    created = generate_jobs_for_schedule(db, schedule, current_user)
    db.commit()
    return {"created_job_count": len(created), "job_ids": [j.id for j in created]}


@router.post("/schedules/{schedule_id}/exceptions", response_model=ScheduleExceptionOut, status_code=201)
def create_exception(schedule_id: str, payload: ScheduleExceptionCreate, db: Session = Depends(get_db),
                      current_user: User = Depends(require_admin_or_manager)):
    """
    Occurrence-level override. If the target occurrence's Job has ALREADY
    been generated, we update that Job directly (it is an independent
    record) instead of only writing the exception -- so the change is
    visible immediately. If the Job doesn't exist yet, the exception is
    simply consulted the next time generation runs for that date.
    """
    schedule = db.query(RecurringSchedule).filter(RecurringSchedule.id == schedule_id).first()
    if not schedule:
        raise NotFoundError("RecurringSchedule", schedule_id)
    if payload.is_skipped and payload.override_date:
        raise ValidationAppError("An exception cannot both skip and move an occurrence")

    exception = ScheduleException(schedule_id=schedule_id, **payload.model_dump())
    db.add(exception)
    db.flush()

    existing_job = (
        db.query(Job)
        .filter(
            Job.schedule_id == schedule_id,
            Job.scheduled_start >= payload.original_occurrence_date.replace(hour=0, minute=0, second=0, microsecond=0),
            Job.scheduled_start < payload.original_occurrence_date.replace(hour=23, minute=59, second=59),
        )
        .first()
    )
    if existing_job:
        if existing_job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            raise ConflictError(f"Cannot modify a job that is already {existing_job.status.value.lower()}")
        if payload.is_skipped:
            existing_job.status = JobStatus.CANCELLED
            existing_job.cancellation_reason = payload.note or "Schedule exception: occurrence skipped"
        else:
            from datetime import time as _time
            if payload.override_date:
                new_date = payload.override_date
            else:
                new_date = existing_job.scheduled_start
            if payload.override_time_of_day:
                h, m = payload.override_time_of_day.split(":")
                new_date = new_date.replace(hour=int(h), minute=int(m))
            duration = existing_job.scheduled_end - existing_job.scheduled_start
            existing_job.scheduled_start = new_date
            existing_job.scheduled_end = new_date + duration
        record_audit(db, current_user, "job.rescheduled_via_exception", "Job", existing_job.id)

    record_audit(db, current_user, "schedule_exception.created", "ScheduleException", exception.id)
    db.commit()
    db.refresh(exception)
    return exception


@router.get("/calendar")
def calendar(
    start: str, end: str,
    employee_id: str | None = None,
    customer_id: str | None = None,
    property_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Powers the calendar month/week/day views. Returns jobs in range
    with the display fields the calendar card needs, pre-joined."""
    from datetime import datetime as dt
    from app.jobs.models import JobAssignment
    from app.employees.models import Employee
    from app.customers.models import Customer, Property
    from app.common.enums import UserRole

    query = db.query(Job).filter(Job.scheduled_start >= dt.fromisoformat(start), Job.scheduled_start <= dt.fromisoformat(end))
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Job.customer_id == current_user.customer_id)
    elif current_user.role.value == "EMPLOYEE" and current_user.employee_id:
        query = query.join(JobAssignment).filter(JobAssignment.employee_id == current_user.employee_id)
    else:
        if customer_id:
            query = query.filter(Job.customer_id == customer_id)
        if employee_id:
            query = query.join(JobAssignment).filter(JobAssignment.employee_id == employee_id)
    if property_id:
        query = query.filter(Job.property_id == property_id)
    if status:
        query = query.filter(Job.status == status)

    jobs = query.order_by(Job.scheduled_start).all()
    results = []
    for job in jobs:
        customer = db.query(Customer).filter(Customer.id == job.customer_id).first()
        prop = db.query(Property).filter(Property.id == job.property_id).first()
        assigned = [
            {"employee_id": a.employee_id, "employee_name": a.employee.full_name}
            for a in job.assignments
        ]
        results.append({
            "id": job.id,
            "reference_number": job.reference_number,
            "customer_name": customer.display_name if customer else None,
            "property_label": prop.label if prop else None,
            "property_address": prop.full_address if prop else None,
            "scheduled_start": job.scheduled_start,
            "scheduled_end": job.scheduled_end,
            "status": job.status,
            "assigned_employees": assigned,
        })
    return results
