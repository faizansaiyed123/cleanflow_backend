from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner, get_current_user, require_staff
from app.users.models import User
from app.audit.service import record_audit
from app.pricing.models import PricingRule
from app.pricing.schemas import PricingRuleUpsert, PricingRuleOut, QuotePreviewRequest
from app.pricing.engine import calculate_quote_price, QuoteCalculationInput

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


@router.get("/rules", response_model=list[PricingRuleOut])
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(PricingRule).all()


@router.put("/rules", response_model=PricingRuleOut)
def upsert_rule(payload: PricingRuleUpsert, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    """Owner-only: pricing configuration directly controls revenue, so it
    is one of the few settings not delegated to managers."""
    rule = db.query(PricingRule).filter(PricingRule.property_type == payload.property_type).first()
    is_new = rule is None
    if not rule:
        rule = PricingRule(property_type=payload.property_type)
        db.add(rule)
    for field, value in payload.model_dump(exclude={"property_type"}).items():
        setattr(rule, field, value)
    db.flush()
    record_audit(db, current_user, "pricing_rule.upserted", "PricingRule", rule.id,
                 new_state=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/preview")
def preview_price(payload: QuotePreviewRequest, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    """Live 'Why this price?' preview used while building a quote, before
    it's saved."""
    result = calculate_quote_price(db, QuoteCalculationInput(**payload.model_dump()))
    return result.as_dict()
