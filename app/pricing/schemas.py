from pydantic import BaseModel, Field

from app.common.enums import PropertyType, CleaningFrequency


class PricingRuleUpsert(BaseModel):
    property_type: PropertyType
    base_rate: float = Field(ge=0)
    rate_per_sqft: float = Field(ge=0)
    rate_per_bathroom: float = Field(ge=0)
    rate_per_floor_above_one: float = Field(ge=0)
    supplies_flat_fee: float = Field(ge=0)
    frequency_adjustments: dict[str, float] = {}
    special_condition_surcharge_percent: float = 0.0
    is_active: bool = True


class PricingRuleOut(PricingRuleUpsert):
    id: str

    class Config:
        from_attributes = True


class QuotePreviewRequest(BaseModel):
    property_type: PropertyType
    square_footage: int
    bathrooms: int
    floors: int
    frequency: CleaningFrequency
    addon_service_ids: list[str] = []
    has_special_conditions: bool = False
    manual_discount_percent: float = 0.0
    manual_discount_reason: str | None = None
