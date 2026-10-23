from datetime import datetime
from pydantic import BaseModel, Field

from app.common.enums import QuoteStatus, PropertyType, CleaningFrequency


class QuoteCreate(BaseModel):
    lead_id: str | None = None
    customer_id: str | None = None
    property_id: str | None = None
    primary_service_id: str

    property_type: PropertyType
    square_footage: int = Field(gt=0)
    bathrooms: int = Field(ge=0)
    floors: int = Field(ge=1)
    frequency: CleaningFrequency
    has_special_conditions: bool = False
    addon_service_ids: list[str] = []
    manual_discount_percent: float = 0.0
    manual_discount_reason: str | None = None

    valid_for_days: int | None = None
    terms: str | None = None
    notes: str | None = None


class QuoteLineItemOut(BaseModel):
    label: str
    amount: float
    kind: str


class QuoteOut(BaseModel):
    id: str
    reference_number: str
    lead_id: str | None
    customer_id: str | None
    property_id: str | None
    property_type: PropertyType
    square_footage: int
    bathrooms: int
    floors: int
    frequency: CleaningFrequency
    addon_service_ids: list
    manual_discount_percent: float
    manual_discount_reason: str | None
    pricing_breakdown: dict
    subtotal: float
    tax_amount: float
    total: float
    status: QuoteStatus
    valid_until: datetime
    terms: str | None
    notes: str | None
    sent_at: datetime | None
    viewed_at: datetime | None
    responded_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class QuoteRejectRequest(BaseModel):
    reason: str | None = None
