from datetime import datetime, timezone, date, timedelta

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.config.settings import get_settings
from app.auth.deps import get_current_user, require_admin_or_manager, require_staff
from app.users.models import User
from app.common.enums import UserRole, JobStatus, PhotoType
from app.common.exceptions import NotFoundError, ForbiddenError, ValidationAppError
from app.jobs.models import Job, JobChecklistItem
from app.jobs.schemas import (
    JobOut, JobListItem, JobAssignRequest, JobRescheduleRequest, JobCancelRequest, CheckInRequest,
    ChecklistItemToggleRequest, JobNoteCreate, JobAssignmentOut,
)
from app.jobs import service as job_service
from app.employees.models import Employee
from app.uploads.storage import save_upload
from app.common.pagination import Page, paginate, apply_sort

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
settings = get_settings()


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = (
        db.query(Job)
        .options(joinedload(Job.assignments), joinedload(Job.checklist_items), joinedload(Job.photos),
                 joinedload(Job.job_notes))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise NotFoundError("Job", job_id)
    return job


def _serialize(db: Session, job: Job) -> JobOut:
    customer = job.customer
    prop = job.site
    return JobOut(
        id=job.id, reference_number=job.reference_number, version=job.version, customer_id=job.customer_id,
        property_id=job.property_id,
        contract_id=job.contract_id, scheduled_start=job.scheduled_start, scheduled_end=job.scheduled_end,
        status=job.status, check_in_at=job.check_in_at, check_out_at=job.check_out_at,
        completed_at=job.completed_at, cancelled_at=job.cancelled_at, cancellation_reason=job.cancellation_reason,
        requires_photo_proof=job.requires_photo_proof, actual_duration_minutes=job.actual_duration_minutes,
        customer_name=customer.display_name if customer else None,
        property_label=prop.label if prop else None,
        property_address=prop.full_address if prop else None,
        assignments=[JobAssignmentOut(employee_id=a.employee_id, employee_name=a.employee.full_name, is_lead=a.is_lead)
                     for a in job.assignments],
        checklist_items=job.checklist_items, photos=job.photos, job_notes=job.job_notes,
    )


class BulkAssignRequest(BaseModel):
    job_ids: list[str]
    employee_ids: list[str]


@router.post("/bulk-assign")
def bulk_assign(payload: BulkAssignRequest, db: Session = Depends(get_db),
                 current_user: User = Depends(require_admin_or_manager)):
    """Assign the same employee(s) to multiple jobs in one action --
    useful when scheduling a crew across a full day at once."""
    results = {"assigned": [], "failed": []}
    for job_id in payload.job_ids:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            results["failed"].append({"job_id": job_id, "reason": "not found"})
            continue
        try:
            job_service.assign_employees(db, job, payload.employee_ids, current_user)
            results["assigned"].append(job_id)
        except Exception as exc:
            results["failed"].append({"job_id": job_id, "reason": str(exc)})
    db.commit()
    return results


@router.get("", response_model=Page[JobListItem])
def list_jobs(
    status: JobStatus | None = None,
    customer_id: str | None = None,
    upcoming_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_dir: str = Query(default="asc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Job)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Job.customer_id == current_user.customer_id)
    elif current_user.role == UserRole.EMPLOYEE:
        from app.jobs.models import JobAssignment
        query = query.join(JobAssignment).filter(JobAssignment.employee_id == current_user.employee_id)
    elif customer_id:
        query = query.filter(Job.customer_id == customer_id)
    if status:
        query = query.filter(Job.status == status)
    if upcoming_only:
        query = query.filter(Job.scheduled_start >= datetime.utcnow())
    query = query.order_by(Job.scheduled_start.desc() if sort_dir == "desc" else Job.scheduled_start.asc())
    jobs, total = paginate(query, page, page_size)
    items = [
        JobListItem(
            id=j.id, reference_number=j.reference_number, scheduled_start=j.scheduled_start,
            scheduled_end=j.scheduled_end, status=j.status,
            customer_name=j.customer.display_name if j.customer else None,
            property_label=j.site.label if j.site else None,
        )
        for j in jobs
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/today", response_model=list[JobListItem])
def my_jobs_today(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The employee mobile dashboard's core view: today's assigned jobs."""
    if current_user.role != UserRole.EMPLOYEE or not current_user.employee_id:
        raise ForbiddenError("This view is for employees")
    from app.jobs.models import JobAssignment
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    jobs = (
        db.query(Job)
        .join(JobAssignment)
        .filter(JobAssignment.employee_id == current_user.employee_id,
                Job.scheduled_start >= today_start, Job.scheduled_start < today_end,
                Job.status != JobStatus.CANCELLED)
        .order_by(Job.scheduled_start)
        .all()
    )
    return [
        JobListItem(id=j.id, reference_number=j.reference_number, scheduled_start=j.scheduled_start,
                    scheduled_end=j.scheduled_end, status=j.status,
                    customer_name=j.customer.display_name if j.customer else None,
                    property_label=j.site.label if j.site else None)
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    if current_user.role == UserRole.CUSTOMER and job.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this job")
    if current_user.role == UserRole.EMPLOYEE:
        assigned_ids = {a.employee_id for a in job.assignments}
        if current_user.employee_id not in assigned_ids:
            raise ForbiddenError("You are not assigned to this job")
    return _serialize(db, job)


@router.get("/{job_id}/health")
def get_job_health(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    job = _get_job_or_404(db, job_id)
    return job_service.job_health(job)


@router.get("/{job_id}/suggested-employees")
def suggested_employees(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    job = _get_job_or_404(db, job_id)
    return job_service.suggest_employees(db, job)


@router.post("/{job_id}/assign", response_model=JobOut)
def assign(job_id: str, payload: JobAssignRequest, db: Session = Depends(get_db),
           current_user: User = Depends(require_admin_or_manager)):
    job = _get_job_or_404(db, job_id)
    job_service.assign_employees(db, job, payload.employee_ids, current_user, payload.expected_version)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/reschedule", response_model=JobOut)
def reschedule(job_id: str, payload: JobRescheduleRequest, db: Session = Depends(get_db),
               current_user: User = Depends(require_admin_or_manager)):
    job = _get_job_or_404(db, job_id)
    job_service.reschedule_job(db, job, payload.scheduled_start, payload.scheduled_end, current_user, payload.expected_version)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: str, payload: JobCancelRequest, db: Session = Depends(get_db),
           current_user: User = Depends(require_admin_or_manager)):
    job = _get_job_or_404(db, job_id)
    job_service.cancel_job(db, job, payload.reason, current_user, payload.expected_version)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


def _require_employee_self(db: Session, job: Job, current_user: User) -> Employee:
    if current_user.role != UserRole.EMPLOYEE or not current_user.employee_id:
        raise ForbiddenError("Only the assigned employee can perform this action")
    assigned_ids = {a.employee_id for a in job.assignments}
    if current_user.employee_id not in assigned_ids:
        raise ForbiddenError("You are not assigned to this job")
    employee = db.query(Employee).filter(Employee.id == current_user.employee_id).first()
    if not employee:
        raise NotFoundError("Employee", current_user.employee_id)
    return employee


@router.post("/{job_id}/check-in", response_model=JobOut)
def check_in(job_id: str, payload: CheckInRequest, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    employee = _require_employee_self(db, job, current_user)
    job_service.check_in(db, job, employee, payload.lat, payload.lng)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/check-out", response_model=JobOut)
def check_out(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    employee = _require_employee_self(db, job, current_user)
    job_service.check_out(db, job, employee)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.patch("/{job_id}/checklist/{item_id}", response_model=JobOut)
def toggle_checklist(job_id: str, item_id: str, payload: ChecklistItemToggleRequest, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    _require_employee_self(db, job, current_user)
    item = db.query(JobChecklistItem).filter(JobChecklistItem.id == item_id, JobChecklistItem.job_id == job_id).first()
    if not item:
        raise NotFoundError("Checklist item", item_id)
    job_service.toggle_checklist_item(db, item, payload.is_completed, payload.note)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/photos", response_model=JobOut)
async def upload_photo(
    job_id: str, photo_type: PhotoType = Form(...), caption: str | None = Form(default=None),
    file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    job = _get_job_or_404(db, job_id)
    employee = _require_employee_self(db, job, current_user)
    key = save_upload("job-photos", job_id, file, settings.max_upload_size_mb * 1024 * 1024, settings.allowed_image_types)
    job_service.add_photo(db, job, employee, photo_type, key, caption)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/notes", response_model=JobOut)
def add_note(job_id: str, payload: JobNoteCreate, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    if current_user.role == UserRole.EMPLOYEE:
        _require_employee_self(db, job, current_user)
    elif current_user.role == UserRole.CUSTOMER and job.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this job")
    job_service.add_note(db, job, current_user, payload.body, payload.is_problem_report)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)


@router.post("/{job_id}/complete", response_model=JobOut)
def complete(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(db, job_id)
    if current_user.role == UserRole.EMPLOYEE:
        _require_employee_self(db, job, current_user)
    elif current_user.role not in (UserRole.OWNER, UserRole.MANAGER):
        raise ForbiddenError("Not authorized to complete this job")
    job_service.complete_job(db, job, current_user)
    db.commit()
    db.refresh(job)
    return _serialize(db, job)
