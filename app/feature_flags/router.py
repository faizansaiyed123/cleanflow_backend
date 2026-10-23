from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner, get_current_user
from app.users.models import User
from app.common.exceptions import NotFoundError
from app.audit.service import record_audit
from app.feature_flags.models import FeatureFlag
from app.feature_flags.schemas import FeatureFlagOut, FeatureFlagToggle
from app.feature_flags.service import ensure_defaults

router = APIRouter(prefix="/api/feature-flags", tags=["feature-flags"])


@router.get("", response_model=list[FeatureFlagOut])
def list_flags(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_defaults(db)
    db.commit()
    return db.query(FeatureFlag).order_by(FeatureFlag.key).all()


@router.patch("/{key}", response_model=FeatureFlagOut)
def toggle_flag(key: str, payload: FeatureFlagToggle, db: Session = Depends(get_db),
                 current_user: User = Depends(require_owner)):
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if not flag:
        raise NotFoundError("FeatureFlag", key)
    previous = {"is_enabled": flag.is_enabled}
    flag.is_enabled = payload.is_enabled
    record_audit(db, current_user, "feature_flag.toggled", "FeatureFlag", flag.id,
                 previous_state=previous, new_state={"is_enabled": payload.is_enabled})
    db.commit()
    db.refresh(flag)
    return flag
