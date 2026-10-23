"""
Backend authorization is enforced here, and ONLY here, via dependencies —
never re-implemented ad hoc inside individual route handlers. Every
protected route declares the roles it accepts through require_roles(...),
and customer-owned-record checks go through require_customer_owns / the
CurrentUser helpers below. The frontend may also hide buttons a role
can't use, but that is a UX nicety, not the security boundary.
"""
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.security import decode_access_token
from app.users.models import User
from app.common.enums import UserRole
from app.common.exceptions import ForbiddenError, AppError
from fastapi import status


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = AppError("Could not validate credentials", status.HTTP_401_UNAUTHORIZED)
    if not authorization or not authorization.startswith("Bearer "):
        raise credentials_error
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise credentials_error
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_roles(*roles: UserRole):
    """Usage: Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))"""

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise ForbiddenError(
                f"This action requires one of the following roles: {', '.join(r.value for r in roles)}"
            )
        return current_user

    return checker


def require_staff(current_user: User = Depends(get_current_user)) -> User:
    """Any internal company user (not a customer)."""
    if current_user.role == UserRole.CUSTOMER:
        raise ForbiddenError("Staff access only")
    return current_user


def require_admin_or_manager(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.MANAGER):
        raise ForbiddenError("Requires owner or manager privileges")
    return current_user


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.OWNER:
        raise ForbiddenError("Requires owner privileges")
    return current_user


def require_financial_access(current_user: User = Depends(get_current_user)) -> User:
    """Employees never see money. Everyone else (owner/manager) does.
    Customers use their own separate, scoped invoice/payment endpoints."""
    if current_user.role not in (UserRole.OWNER, UserRole.MANAGER):
        raise ForbiddenError("Financial data is restricted to owner/manager roles")
    return current_user
