from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner
from app.users.models import User
from app.audit.models import AuditLog
from app.audit.schemas import AuditLogOut
from app.common.pagination import Page, paginate

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("", response_model=Page[AuditLogOut])
def list_audit_logs(
    entity_type: str | None = None,
    entity_id: str | None = None,
    q: str | None = Query(default=None, description="Filter by action, e.g. 'quote.'"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Audit history is restricted to the owner: it can reveal sensitive
    operational and financial history across the whole company."""
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if q:
        query = query.filter(AuditLog.action.ilike(f"%{q}%"))
    query = query.order_by(AuditLog.created_at.desc())
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)
