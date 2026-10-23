from sqlalchemy.orm import Session
from app.feature_flags.models import FeatureFlag

DEFAULT_FLAGS = {
    "auto_invoice_on_completion": "When a job completes, automatically generate and send its invoice "
                                   "instead of requiring a manager to do it manually.",
    "webhooks_enabled": "Allow outbound webhook deliveries to fire. Kept as a kill-switch independent of "
                         "individual endpoint configuration.",
    "smart_assignment_v2": "Placeholder for a future ranking-model-based assignment suggester (currently "
                            "unused; demonstrates how a flag stages work before the code behind it ships).",
}


def is_enabled(db: Session, key: str) -> bool:
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    return bool(flag and flag.is_enabled)


def ensure_defaults(db: Session) -> None:
    for key, description in DEFAULT_FLAGS.items():
        if not db.query(FeatureFlag).filter(FeatureFlag.key == key).first():
            db.add(FeatureFlag(key=key, is_enabled=False, description=description))
