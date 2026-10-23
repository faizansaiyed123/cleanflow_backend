from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from app.common.enums import LeadSource, LeadStatus, PropertyType, CleaningFrequency


class PublicQuoteRequest(BaseModel):
    """What a visitor submits from the public 'Request a Quote' page."""
    contact_name: str
    company_name: str | None = None
    email: EmailStr
    phone: str
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    property_type: PropertyType = PropertyType.OFFICE
    square_footage: int | None = Field(default=None, gt=0)
    bathrooms: int | None = Field(default=None, ge=0)
    floors: int | None = Field(default=None, ge=1)
    frequency: CleaningFrequency | None = None
    requested_services: list[str] = []
    requested_addons: list[str] = []
    preferred_start_date: datetime | None = None
    preferred_time: str | None = None
    notes: str | None = None


class PublicQuoteRequestResponse(BaseModel):
    reference_number: str
    message: str = "Thanks! Your request has been received. Our team will follow up shortly."


class LeadUpdate(BaseModel):
    status: LeadStatus | None = None
    estimated_value: float | None = None
    notes: str | None = None
    last_contacted_at: datetime | None = None


class LeadOut(BaseModel):
    id: str
    reference_number: str
    contact_name: str
    company_name: str | None
    email: str
    phone: str
    address_line1: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    property_type: PropertyType
    square_footage: int | None
    bathrooms: int | None
    floors: int | None
    frequency: CleaningFrequency | None
    requested_services: list
    requested_addons: list
    notes: str | None
    source: LeadSource
    status: LeadStatus
    estimated_value: float | None
    created_at: datetime
    last_contacted_at: datetime | None
    converted_customer_id: str | None

    class Config:
        from_attributes = True


class LeadConvertRequest(BaseModel):
    """Convert a QUALIFIED lead into a real Customer (+ optional Property)."""
    create_property: bool = True
