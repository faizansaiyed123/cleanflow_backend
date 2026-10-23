from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner, get_current_user
from app.auth.security import hash_password, verify_password
from app.users.models import User
from app.users.schemas import StaffUserCreate, UserOut, PasswordChangeRequest
from app.common.enums import UserRole
from app.common.exceptions import ConflictError, ValidationAppError
from app.audit.service import record_audit
from app.common.pagination import Page, paginate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=Page[UserOut])
def list_users(page: int = 1, page_size: int = 25, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    """Owner-only: full account/permission visibility for the company."""
    query = db.query(User).order_by(User.role, User.full_name)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=UserOut, status_code=201)
def create_staff_user(payload: StaffUserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    if payload.role == UserRole.CUSTOMER:
        raise ValidationAppError("Customer portal logins are provisioned automatically when a quote is created, not via this endpoint")
    if payload.role == UserRole.EMPLOYEE and not payload.employee_id:
        raise ValidationAppError("employee_id is required when creating an EMPLOYEE login")
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise ConflictError("A user with this email already exists")

    user = User(
        email=payload.email.lower(), hashed_password=hash_password(payload.password), full_name=payload.full_name,
        role=payload.role, employee_id=payload.employee_id,
    )
    db.add(user)
    db.flush()
    record_audit(db, current_user, "user.created", "User", user.id, new_state={"role": payload.role.value})
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(user_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    from app.common.exceptions import NotFoundError
    if user_id == current_user.id:
        raise ConflictError("You cannot deactivate your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User", user_id)
    user.is_active = False
    record_audit(db, current_user, "user.deactivated", "User", user.id)
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/change-password")
def change_my_password(payload: PasswordChangeRequest, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise ValidationAppError("Current password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    record_audit(db, current_user, "user.password_changed", "User", current_user.id)
    db.commit()
    return {"ok": True}
