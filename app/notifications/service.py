from sqlalchemy.orm import Session

from app.notifications.models import Notification
from app.users.models import User
from app.common.enums import UserRole, NotificationType


def notify_user(db: Session, user_id: str, type_: str, title: str, body: str | None = None,
                 link_entity_type: str | None = None, link_entity_id: str | None = None) -> Notification:
    note = Notification(
        user_id=user_id, type=NotificationType(type_), title=title, body=body,
        link_entity_type=link_entity_type, link_entity_id=link_entity_id,
    )
    db.add(note)
    return note


def notify_role(db: Session, role: str, type_: str, title: str, body: str | None = None,
                 link_entity_type: str | None = None, link_entity_id: str | None = None) -> list[Notification]:
    """Fan out a notification to every active user with the given role
    (e.g. every MANAGER/OWNER gets pinged about a new lead)."""
    roles = [UserRole(role)] if role != "STAFF" else [UserRole.OWNER, UserRole.MANAGER]
    users = db.query(User).filter(User.role.in_(roles), User.is_active.is_(True)).all()
    return [notify_user(db, u.id, type_, title, body, link_entity_type, link_entity_id) for u in users]
