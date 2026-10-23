from sqlalchemy import Column, String, Float, Boolean, JSON, Enum
from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import PropertyType


class PricingRule(Base, UUIDPKMixin, TimestampMixin):
    """
    One configurable pricing rule per property type. Nothing about these
    numbers is hardcoded in the quote engine (see app/pricing/engine.py) -
    admins edit this table via the settings UI and every future quote
    picks up the change immediately. Quotes snapshot the resulting
    breakdown at generation time (see Quote.pricing_breakdown) so past
    quotes stay explainable even after rules change.
    """

    __tablename__ = "pricing_rules"

    property_type = Column(Enum(PropertyType), nullable=False, unique=True)

    base_rate = Column(Float, nullable=False, default=75.0)
    rate_per_sqft = Column(Float, nullable=False, default=0.05)
    rate_per_bathroom = Column(Float, nullable=False, default=20.0)
    rate_per_floor_above_one = Column(Float, nullable=False, default=15.0)
    supplies_flat_fee = Column(Float, nullable=False, default=20.0)

    # Multiplicative adjustment applied to the subtotal-so-far, keyed by
    # CleaningFrequency value, e.g. {"DAILY": -0.15, "WEEKLY": -0.10, ...}
    # Negative = discount for more frequent recurring service.
    frequency_adjustments = Column(JSON, nullable=False, default=dict)

    # Percent surcharge applied for special/hazardous conditions flagged
    # on the quote request (e.g. biohazard, post-construction).
    special_condition_surcharge_percent = Column(Float, nullable=False, default=0.0)

    is_active = Column(Boolean, default=True, nullable=False)
