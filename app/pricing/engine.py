"""
The Smart Quote Engine.

Design goal: nothing here is a hardcoded number. Every coefficient comes
from the PricingRule row for the property's type (editable by admins in
Settings). The engine's only job is to combine those configured
coefficients with the specifics of a given request (square footage,
bathrooms, floors, frequency, add-ons, special conditions, discount) into
a fully itemized, human-readable breakdown.

That breakdown is what powers "Why this price?" on the quote screen, and
it is persisted verbatim onto the Quote row at generation time -- so if
an admin changes pricing rules next month, quotes generated last month
still show exactly how their number was produced.
"""
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.pricing.models import PricingRule
from app.services.models import Service
from app.common.enums import PropertyType, CleaningFrequency
from app.common.exceptions import ValidationAppError


@dataclass
class PriceLineItem:
    label: str
    amount: float
    kind: str = "charge"  # "charge" | "discount" | "surcharge"


@dataclass
class QuoteCalculationInput:
    property_type: PropertyType
    square_footage: int
    bathrooms: int
    floors: int
    frequency: CleaningFrequency
    addon_service_ids: list[str] = field(default_factory=list)
    has_special_conditions: bool = False
    manual_discount_percent: float = 0.0
    manual_discount_reason: str | None = None


@dataclass
class QuoteCalculationResult:
    line_items: list[PriceLineItem]
    subtotal: float
    total: float

    def as_dict(self) -> dict:
        return {
            "line_items": [
                {"label": li.label, "amount": round(li.amount, 2), "kind": li.kind}
                for li in self.line_items
            ],
            "subtotal": round(self.subtotal, 2),
            "total": round(self.total, 2),
        }


def get_active_rule(db: Session, property_type: PropertyType) -> PricingRule:
    rule = (
        db.query(PricingRule)
        .filter(PricingRule.property_type == property_type, PricingRule.is_active.is_(True))
        .first()
    )
    if not rule:
        raise ValidationAppError(
            f"No active pricing rule configured for property type '{property_type.value}'. "
            "An owner must configure pricing in Settings before quotes can be generated."
        )
    return rule


def calculate_quote_price(db: Session, calc_input: QuoteCalculationInput) -> QuoteCalculationResult:
    if calc_input.square_footage <= 0:
        raise ValidationAppError("Square footage must be greater than zero")
    if calc_input.bathrooms < 0 or calc_input.floors < 1:
        raise ValidationAppError("Bathrooms cannot be negative and floors must be at least 1")

    rule = get_active_rule(db, calc_input.property_type)
    items: list[PriceLineItem] = []

    # 1. Base rate for the service type
    items.append(PriceLineItem("Base service", rule.base_rate))
    running_total = rule.base_rate

    # 2. Square footage cost
    sqft_cost = calc_input.square_footage * rule.rate_per_sqft
    items.append(PriceLineItem(f"Square footage ({calc_input.square_footage} sq ft)", sqft_cost))
    running_total += sqft_cost

    # 3. Bathroom cost
    if calc_input.bathrooms > 0:
        bathroom_cost = calc_input.bathrooms * rule.rate_per_bathroom
        items.append(PriceLineItem(f"Bathrooms ({calc_input.bathrooms})", bathroom_cost))
        running_total += bathroom_cost

    # 4. Floor adjustment (first floor included in base; extra floors cost more)
    extra_floors = max(calc_input.floors - 1, 0)
    if extra_floors > 0:
        floor_cost = extra_floors * rule.rate_per_floor_above_one
        items.append(PriceLineItem(f"Additional floors ({extra_floors})", floor_cost))
        running_total += floor_cost

    # 5. Frequency adjustment (percentage of running subtotal so far)
    freq_pct = (rule.frequency_adjustments or {}).get(calc_input.frequency.value, 0.0)
    if freq_pct:
        freq_amount = running_total * freq_pct
        label = f"Frequency adjustment ({calc_input.frequency.value.title()})"
        items.append(PriceLineItem(label, freq_amount, kind="discount" if freq_amount < 0 else "charge"))
        running_total += freq_amount

    # 6. Add-ons (each priced from the Service catalog)
    if calc_input.addon_service_ids:
        addons = db.query(Service).filter(Service.id.in_(calc_input.addon_service_ids)).all()
        found_ids = {a.id for a in addons}
        missing = set(calc_input.addon_service_ids) - found_ids
        if missing:
            raise ValidationAppError(f"Unknown add-on service id(s): {', '.join(missing)}")
        for addon in addons:
            items.append(PriceLineItem(f"Add-on: {addon.name}", addon.base_rate))
            running_total += addon.base_rate

    # 7. Supplies flat fee
    if rule.supplies_flat_fee:
        items.append(PriceLineItem("Supplies", rule.supplies_flat_fee))
        running_total += rule.supplies_flat_fee

    # 8. Special-condition surcharge
    if calc_input.has_special_conditions and rule.special_condition_surcharge_percent:
        surcharge = running_total * rule.special_condition_surcharge_percent
        items.append(PriceLineItem("Special conditions surcharge", surcharge, kind="surcharge"))
        running_total += surcharge

    subtotal = running_total

    # 9. Manual discount (e.g. sales negotiation), applied last and always visible
    total = subtotal
    if calc_input.manual_discount_percent:
        if not (0 <= calc_input.manual_discount_percent <= 100):
            raise ValidationAppError("Discount percent must be between 0 and 100")
        discount_amount = subtotal * (calc_input.manual_discount_percent / 100)
        label = "Discount" + (f" ({calc_input.manual_discount_reason})" if calc_input.manual_discount_reason else "")
        items.append(PriceLineItem(label, -discount_amount, kind="discount"))
        total = subtotal - discount_amount

    return QuoteCalculationResult(line_items=items, subtotal=subtotal, total=total)
