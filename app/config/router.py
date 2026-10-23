from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner, get_current_user
from app.users.models import User
from app.audit.service import record_audit
from app.config.models import CompanySetting
from app.config.schemas import CompanySettingUpdate, CompanySettingOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _get_or_create_settings(db: Session) -> CompanySetting:
    settings_row = db.query(CompanySetting).first()
    if not settings_row:
        settings_row = CompanySetting()
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


@router.get("", response_model=CompanySettingOut)
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_or_create_settings(db)


@router.patch("", response_model=CompanySettingOut)
def update_settings(payload: CompanySettingUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    settings_row = _get_or_create_settings(db)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(settings_row, field, value)
    record_audit(db, current_user, "company_settings.updated", "CompanySetting", settings_row.id, new_state=changes)
    db.commit()
    db.refresh(settings_row)
    return settings_row
