from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.schemas import LoginRequest, TokenResponse, MeResponse
from app.auth.security import verify_password, create_access_token
from app.auth.deps import get_current_user
from app.users.models import User
from app.common.exceptions import AppError
from app.observability.rate_limit_deps import rate_limited
from app.observability.rate_limit import login_limiter
from fastapi import status

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limited(login_limiter, "login"))])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise AppError("Incorrect email or password", status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        raise AppError("This account has been deactivated", status.HTTP_401_UNAUTHORIZED)
    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(
        access_token=token, role=user.role, user_id=user.id, full_name=user.full_name
    )


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
