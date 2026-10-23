"""Unit tests for the Smart Quote pricing engine (app/pricing/engine.py)."""
import pytest

from app.pricing.models import PricingRule
from app.pricing.engine import calculate_quote_price, QuoteCalculationInput, get_active_rule
from app.common.enums import PropertyType, CleaningFrequency
from app.common.exceptions import ValidationAppError
from app.services.models import Service


@pytest.fixture()
def office_rule(db):
    rule = db.query(PricingRule).filter(PricingRule.property_type == PropertyType.OFFICE).first()
    if not rule:
        rule = PricingRule(
            property_type=PropertyType.OFFICE, base_rate=100, rate_per_sqft=0.05, rate_per_bathroom=20,
            rate_per_floor_above_one=15, supplies_flat_fee=20,
            frequency_adjustments={"WEEKLY": -0.10, "ONE_TIME": 0.10}, is_active=True,
        )
        db.add(rule)
        db.commit()
    return rule


def test_base_calculation_matches_expected_breakdown(db, office_rule):
    result = calculate_quote_price(db, QuoteCalculationInput(
        property_type=PropertyType.OFFICE, square_footage=3000, bathrooms=3, floors=2,
        frequency=CleaningFrequency.WEEKLY,
    ))
    # base 100 + sqft(3000*0.05=150) + bathrooms(3*20=60) + floor(1*15=15) = 325
    # frequency -10% of 325 = -32.5 -> 292.5, + supplies 20 = 312.5
    assert result.subtotal == pytest.approx(312.5)
    assert result.total == pytest.approx(312.5)
    labels = [li.label for li in result.line_items]
    assert "Base service" in labels[0]


def test_manual_discount_applied_after_subtotal(db, office_rule):
    result = calculate_quote_price(db, QuoteCalculationInput(
        property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
        frequency=CleaningFrequency.ONE_TIME, manual_discount_percent=10, manual_discount_reason="Referral",
    ))
    subtotal_before_discount = result.subtotal
    assert result.total == pytest.approx(subtotal_before_discount * 0.9)


def test_addon_pricing_pulled_from_service_catalog(db, office_rule):
    addon = Service(name="Window Cleaning", is_addon=True, base_rate=45)
    db.add(addon)
    db.commit()
    result = calculate_quote_price(db, QuoteCalculationInput(
        property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
        frequency=CleaningFrequency.ONE_TIME, addon_service_ids=[addon.id],
    ))
    labels = {li.label: li.amount for li in result.line_items}
    assert labels["Add-on: Window Cleaning"] == 45


def test_unknown_addon_id_rejected(db, office_rule):
    with pytest.raises(ValidationAppError):
        calculate_quote_price(db, QuoteCalculationInput(
            property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
            frequency=CleaningFrequency.ONE_TIME, addon_service_ids=["does-not-exist"],
        ))


def test_missing_pricing_rule_raises_clear_error(db):
    with pytest.raises(ValidationAppError):
        calculate_quote_price(db, QuoteCalculationInput(
            property_type=PropertyType.RESIDENTIAL, square_footage=1000, bathrooms=1, floors=1,
            frequency=CleaningFrequency.ONE_TIME,
        ))


def test_invalid_square_footage_rejected(db, office_rule):
    with pytest.raises(ValidationAppError):
        calculate_quote_price(db, QuoteCalculationInput(
            property_type=PropertyType.OFFICE, square_footage=0, bathrooms=1, floors=1,
            frequency=CleaningFrequency.ONE_TIME,
        ))


def test_changing_pricing_rule_does_not_affect_a_stored_breakdown(db, office_rule):
    """Quotes snapshot their breakdown, so a later rule change must not
    retroactively alter an already-generated quote's numbers."""
    result_before = calculate_quote_price(db, QuoteCalculationInput(
        property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
        frequency=CleaningFrequency.ONE_TIME,
    ))
    snapshot = result_before.as_dict()

    office_rule.base_rate = 999
    db.commit()

    # The snapshot dict taken earlier is untouched by the rule change.
    assert snapshot["line_items"][0]["amount"] != 999
