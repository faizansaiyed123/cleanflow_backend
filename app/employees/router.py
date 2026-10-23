from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_admin_or_manager, require_staff
from app.users.models import User
from app.audit.service import record_audit
from app.employees.models import Employee
from app.employees.schemas import EmployeeCreate, EmployeeUpdate, EmployeeOut

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    q: str | None = Query(default=None),
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    query = db.query(Employee)
    if active_only:
        query = query.filter(Employee.is_active.is_(True), Employee.is_archived.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter((Employee.full_name.ilike(like)) | (Employee.email.ilike(like)))
    return query.order_by(Employee.full_name).all()


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(
    payload: EmployeeCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)
):
    employee = Employee(**payload.model_dump())
    db.add(employee)
    db.flush()
    record_audit(db, current_user, "employee.created", "Employee", employee.id, new_state=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(employee)
    return employee


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    from app.common.exceptions import NotFoundError
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise NotFoundError("Employee", employee_id)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: str, payload: EmployeeUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    from app.common.exceptions import NotFoundError
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise NotFoundError("Employee", employee_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(employee, field, value)
    record_audit(db, current_user, "employee.updated", "Employee", employee.id, new_state=changes)
    db.commit()
    db.refresh(employee)
    return employee


@router.get("/{employee_id}/workload")
def employee_workload(employee_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    """Count of upcoming assigned jobs -- used by the smart-assignment
    suggester and by managers checking someone isn't overloaded."""
    from datetime import datetime, timezone
    from app.jobs.models import Job, JobAssignment
    from app.common.enums import JobStatus

    upcoming = (
        db.query(Job)
        .join(JobAssignment, JobAssignment.job_id == Job.id)
        .filter(
            JobAssignment.employee_id == employee_id,
            Job.scheduled_start >= datetime.utcnow(),
            Job.status.notin_([JobStatus.CANCELLED, JobStatus.COMPLETED]),
        )
        .count()
    )
    return {"employee_id": employee_id, "upcoming_job_count": upcoming}
