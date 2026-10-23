from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import get_current_user, require_admin_or_manager
from app.users.models import User
from app.common.enums import UserRole, ContractStatus, JobStatus
from app.common.exceptions import NotFoundError, ForbiddenError
from app.contracts.models import Contract
from app.contracts.schemas import ContractOut, ContractCancelRequest, ContractRenewRequest, ContractHealthOut
from app.contracts import service as contract_service
from app.jobs.models import Job
from app.invoices.models import Invoice
from app.feedback.models import Feedback
from app.common.pagination import Page, paginate, apply_sort

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


def _get_contract_or_404(db: Session, contract_id: str) -> Contract:
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise NotFoundError("Contract", contract_id)
    return contract


def _enforce_access(contract: Contract, current_user: User):
    if current_user.role == UserRole.CUSTOMER and contract.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this contract")


@router.get("", response_model=Page[ContractOut])
def list_contracts(status: ContractStatus | None = None, customer_id: str | None = None,
                    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
                    sort_by: str = Query(default="created_at"), sort_dir: str = Query(default="desc"),
                    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Contract)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Contract.customer_id == current_user.customer_id)
    elif customer_id:
        query = query.filter(Contract.customer_id == customer_id)
    if status:
        query = query.filter(Contract.status == status)
    query = apply_sort(query, Contract, sort_by, sort_dir)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(contract_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    contract = _get_contract_or_404(db, contract_id)
    _enforce_access(contract, current_user)
    return contract


@router.post("/{contract_id}/pause", response_model=ContractOut)
def pause_contract(contract_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    contract = _get_contract_or_404(db, contract_id)
    contract_service.pause_contract(db, contract, current_user)
    db.commit()
    db.refresh(contract)
    return contract


@router.post("/{contract_id}/resume", response_model=ContractOut)
def resume_contract(contract_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    contract = _get_contract_or_404(db, contract_id)
    contract_service.resume_contract(db, contract, current_user)
    db.commit()
    db.refresh(contract)
    return contract


@router.post("/{contract_id}/cancel", response_model=ContractOut)
def cancel_contract(contract_id: str, payload: ContractCancelRequest, db: Session = Depends(get_db),
                     current_user: User = Depends(require_admin_or_manager)):
    contract = _get_contract_or_404(db, contract_id)
    contract_service.cancel_contract(db, contract, payload.reason, current_user)
    db.commit()
    db.refresh(contract)
    return contract


@router.post("/{contract_id}/renew", response_model=ContractOut)
def renew_contract(contract_id: str, payload: ContractRenewRequest, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin_or_manager)):
    contract = _get_contract_or_404(db, contract_id)
    renewed = contract_service.renew_contract(db, contract, payload.new_end_date, current_user)
    db.commit()
    db.refresh(renewed)
    return renewed


@router.get("/{contract_id}/health", response_model=ContractHealthOut)
def contract_health(contract_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Contract Health: a single glance at whether this account is
    running smoothly -- completion rate, revenue, feedback, and how
    close it is to expiring."""
    contract = _get_contract_or_404(db, contract_id)
    _enforce_access(contract, current_user)

    from sqlalchemy import func

    # Single grouped-count query instead of loading every Job row and
    # branching on status in Python -- scales the same whether the
    # contract has 10 jobs or 10,000.
    status_counts = dict(
        db.query(Job.status, func.count(Job.id)).filter(Job.contract_id == contract.id).group_by(Job.status).all()
    )
    completed_count = status_counts.get(JobStatus.COMPLETED, 0)
    problem_count = status_counts.get(JobStatus.CANCELLED, 0) + status_counts.get(JobStatus.NO_SHOW, 0)
    finished_total = completed_count + problem_count
    completion_rate = (completed_count / finished_total) if finished_total else None

    total_revenue, outstanding = db.query(
        func.coalesce(func.sum(Invoice.total), 0.0),
        func.coalesce(func.sum(Invoice.total - Invoice.amount_paid), 0.0),
    ).filter(Invoice.contract_id == contract.id).first()

    # Average rating via a join, not a Python loop over each job's
    # lazily-loaded .feedback relationship (that was one query per job).
    avg_rating = (
        db.query(func.avg(Feedback.rating))
        .join(Job, Job.id == Feedback.job_id)
        .filter(Job.contract_id == contract.id)
        .scalar()
    )
    avg_rating = round(avg_rating, 2) if avg_rating is not None else None

    days_until = None
    is_expiring_soon = False
    if contract.end_date:
        days_until = (contract.end_date - datetime.utcnow()).days
        is_expiring_soon = 0 <= days_until <= 30

    return ContractHealthOut(
        contract_id=contract.id,
        status=contract.status,
        is_expiring_soon=is_expiring_soon,
        days_until_expiration=days_until,
        completed_job_count=completed_count,
        cancelled_or_noshow_job_count=problem_count,
        job_completion_rate=completion_rate,
        total_revenue_invoiced=round(total_revenue or 0.0, 2),
        outstanding_invoice_total=round(max(outstanding or 0.0, 0.0), 2),
        average_feedback_rating=avg_rating,
    )
