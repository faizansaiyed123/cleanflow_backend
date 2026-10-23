"""
Job lifecycle business rules -- assignment, check-in/out, checklist
completion, and the completion gate (required checklist items + proof
photos). This is the module that makes "an employee cannot silently
mark a job done without doing the work" true in the backend, where it
can't be bypassed by the frontend.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.common.enums import JobStatus, PhotoType
from app.common.exceptions import ConflictError, ValidationAppError, NotFoundError
from app.common.concurrency import check_and_bump_version
from app.audit.service import record_audit
from app.jobs.models import Job, JobAssignment, JobChecklistItem, JobPhoto, JobNote
from app.employees.models import Employee
from app.users.models import User
from app.notifications.service import notify_role  # noqa: F401 -- kept for any ad hoc direct notification needs
from app.events.bus import publish, EventType


def assign_employees(db: Session, job: Job, employee_ids: list[str], actor: User,
                      expected_version: int | None = None) -> Job:
    if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
        raise ConflictError(f"Cannot assign employees to a job that is {job.status.value.lower()}")
    if not employee_ids:
        raise ValidationAppError("At least one employee must be assigned")
    check_and_bump_version(job, expected_version, "Job")

    employees = db.query(Employee).filter(Employee.id.in_(employee_ids), Employee.is_active.is_(True)).all()
    if len(employees) != len(set(employee_ids)):
        raise NotFoundError("One or more employees")

    # Basic double-booking guard: warn-level conflict check (same employee,
    # overlapping time window, different job).
    from app.jobs.models import Job as JobModel
    for emp_id in employee_ids:
        conflict = (
            db.query(JobModel)
            .join(JobAssignment)
            .filter(
                JobAssignment.employee_id == emp_id,
                JobModel.id != job.id,
                JobModel.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]),
                JobModel.scheduled_start < job.scheduled_end,
                JobModel.scheduled_end > job.scheduled_start,
            )
            .first()
        )
        if conflict:
            raise ConflictError(
                f"Employee is already assigned to job {conflict.reference_number} during this time window"
            )

    db.query(JobAssignment).filter(JobAssignment.job_id == job.id).delete()
    for i, emp in enumerate(employees):
        db.add(JobAssignment(job_id=job.id, employee_id=emp.id, is_lead=(i == 0)))

    if job.status == JobStatus.SCHEDULED:
        job.status = JobStatus.ASSIGNED

    record_audit(db, actor, "job.assigned", "Job", job.id, new_state={"employee_ids": employee_ids})
    employee_user_ids = [e.user.id for e in employees if e.user]
    if employee_user_ids:
        publish(db, EventType.JOB_ASSIGNED, {
            "job_id": job.id, "reference_number": job.reference_number,
            "employee_user_ids": employee_user_ids,
            "scheduled_start_label": job.scheduled_start.strftime("%b %d, %I:%M %p"),
        })
    return job


def suggest_employees(db: Session, job: Job, limit: int = 5) -> list[dict]:
    """Smart assignment: rank active employees by (1) no scheduling
    conflict, (2) lower current workload, as a simple, explainable
    heuristic rather than a black box."""
    from app.jobs.models import Job as JobModel

    candidates = db.query(Employee).filter(Employee.is_active.is_(True), Employee.is_archived.is_(False)).all()
    scored = []
    for emp in candidates:
        conflict = (
            db.query(JobModel)
            .join(JobAssignment)
            .filter(
                JobAssignment.employee_id == emp.id,
                JobModel.id != job.id,
                JobModel.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]),
                JobModel.scheduled_start < job.scheduled_end,
                JobModel.scheduled_end > job.scheduled_start,
            )
            .first()
        )
        if conflict:
            continue
        upcoming_count = (
            db.query(JobModel)
            .join(JobAssignment)
            .filter(
                JobAssignment.employee_id == emp.id,
                JobModel.scheduled_start >= datetime.utcnow(),
                JobModel.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]),
            )
            .count()
        )
        scored.append({"employee_id": emp.id, "employee_name": emp.full_name, "current_workload": upcoming_count,
                        "skills": emp.skills})
    scored.sort(key=lambda s: s["current_workload"])
    return scored[:limit]


def check_in(db: Session, job: Job, employee: Employee, lat: str | None, lng: str | None) -> Job:
    if job.status not in (JobStatus.ASSIGNED, JobStatus.SCHEDULED):
        raise ConflictError(f"Cannot check in to a job that is {job.status.value.lower()}")
    if job.check_in_at:
        raise ConflictError("Already checked in to this job")
    assigned_ids = {a.employee_id for a in job.assignments}
    if employee.id not in assigned_ids:
        raise ConflictError("You are not assigned to this job")

    job.check_in_at = datetime.utcnow()
    job.check_in_lat = lat
    job.check_in_lng = lng
    job.status = JobStatus.IN_PROGRESS
    record_audit(db, None, "job.checked_in", "Job", job.id, new_state={"employee_id": employee.id})
    return job


def check_out(db: Session, job: Job, employee: Employee) -> Job:
    if not job.check_in_at:
        raise ConflictError("Cannot check out before checking in")
    if job.check_out_at:
        raise ConflictError("Already checked out of this job")
    if job.status == JobStatus.COMPLETED:
        raise ConflictError("Job is already completed")

    job.check_out_at = datetime.utcnow()
    record_audit(db, None, "job.checked_out", "Job", job.id, new_state={"employee_id": employee.id})
    return job


def toggle_checklist_item(db: Session, item: JobChecklistItem, is_completed: bool, note: str | None) -> JobChecklistItem:
    if item.job.status == JobStatus.COMPLETED:
        raise ConflictError("Cannot modify the checklist of a completed job")
    item.is_completed = is_completed
    item.completed_at = datetime.utcnow() if is_completed else None
    if note is not None:
        item.note = note
    return item


def add_photo(db: Session, job: Job, employee: Employee | None, photo_type: PhotoType, storage_key: str,
              caption: str | None) -> JobPhoto:
    photo = JobPhoto(job_id=job.id, uploaded_by_employee_id=employee.id if employee else None,
                      photo_type=photo_type, storage_key=storage_key, caption=caption)
    db.add(photo)
    return photo


def add_note(db: Session, job: Job, author: User | None, body: str, is_problem_report: bool) -> JobNote:
    note = JobNote(job_id=job.id, author_user_id=author.id if author else None, body=body,
                    is_problem_report=is_problem_report)
    db.add(note)
    return note


def complete_job(db: Session, job: Job, actor: User) -> Job:
    """
    The completion gate. A job CANNOT be completed while:
      - any required checklist item is incomplete, or
      - proof-of-service photos are required but before/after are missing.
    This is enforced here, server-side, so it can't be bypassed by a
    client skipping steps in the mobile UI.
    """
    if job.status == JobStatus.COMPLETED:
        raise ConflictError("Job is already completed")
    if job.status == JobStatus.CANCELLED:
        raise ConflictError("Cannot complete a cancelled job")
    if not job.check_in_at:
        raise ConflictError("Job must be checked in before it can be completed")
    if not job.check_out_at:
        raise ConflictError("Job must be checked out before it can be completed")

    incomplete_required = [i for i in job.checklist_items if i.is_required and not i.is_completed]
    if incomplete_required:
        labels = ", ".join(i.label for i in incomplete_required)
        raise ConflictError(f"Required checklist items are not complete: {labels}")

    if job.requires_photo_proof:
        photo_types = {p.photo_type for p in job.photos}
        missing = [t.value for t in (PhotoType.BEFORE, PhotoType.AFTER) if t not in photo_types]
        if missing:
            raise ConflictError(f"Missing required proof-of-service photo(s): {', '.join(missing)}")

    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.utcnow()
    record_audit(db, actor, "job.completed", "Job", job.id)
    publish(db, EventType.JOB_COMPLETED, {"job_id": job.id, "reference_number": job.reference_number})
    from app.observability.metrics import JOBS_COMPLETED
    JOBS_COMPLETED.inc()
    return job


def cancel_job(db: Session, job: Job, reason: str, actor: User, expected_version: int | None = None) -> Job:
    if job.status == JobStatus.COMPLETED:
        raise ConflictError("A completed job cannot be silently returned to cancelled/scheduled status")
    check_and_bump_version(job, expected_version, "Job")
    job.status = JobStatus.CANCELLED
    job.cancellation_reason = reason
    job.cancelled_at = datetime.utcnow()
    record_audit(db, actor, "job.cancelled", "Job", job.id, new_state={"reason": reason})
    return job


def reschedule_job(db: Session, job: Job, new_start, new_end, actor: User, expected_version: int | None = None) -> Job:
    if job.status in (JobStatus.COMPLETED,):
        raise ConflictError("A completed job cannot be rescheduled")
    check_and_bump_version(job, expected_version, "Job")
    previous = {"scheduled_start": job.scheduled_start.isoformat()}
    job.scheduled_start = new_start
    job.scheduled_end = new_end
    record_audit(db, actor, "job.rescheduled", "Job", job.id, previous_state=previous,
                 new_state={"scheduled_start": new_start.isoformat()})
    publish(db, EventType.JOB_RESCHEDULED, {"job_id": job.id, "reference_number": job.reference_number})
    return job


def job_health(job: Job) -> dict:
    """A simple, explainable operational health signal per job -- used by
    managers to spot incomplete workflows at a glance."""
    has_assignment = len(job.assignments) > 0
    has_checkin = job.check_in_at is not None
    required_items = [i for i in job.checklist_items if i.is_required]
    checklist_complete = all(i.is_completed for i in required_items) if required_items else True
    photo_types = {p.photo_type for p in job.photos}
    has_required_photos = (not job.requires_photo_proof) or (
        PhotoType.BEFORE in photo_types and PhotoType.AFTER in photo_types
    )
    is_completed = job.status == JobStatus.COMPLETED
    has_feedback = job.feedback is not None

    steps = {
        "assigned": has_assignment,
        "checked_in": has_checkin,
        "checklist_complete": checklist_complete,
        "photos_complete": has_required_photos,
        "completed": is_completed,
        "feedback_received": has_feedback,
    }
    score = sum(1 for v in steps.values() if v)
    return {"steps": steps, "score": score, "of": len(steps)}
