from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.users.models import User


def record_audit(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str,
    previous_state: dict | None = None,
    new_state: dict | None = None,
) -> None:
    """Every state-changing action that matters for accountability
    (quote accepted, contract cancelled, job reassigned, invoice edited,
    payment recorded, permission changed) should call this. Kept as a
    single, simple function rather than a decorator/middleware so call
    sites stay explicit about *what* they're logging and *why*."""

    log = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        previous_state=previous_state,
        new_state=new_state,
    )
    db.add(log)
