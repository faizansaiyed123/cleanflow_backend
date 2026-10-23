from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from app.common.enums import PropertyType


class PropertyCreate(BaseModel):
    label: str
    address_line1: str
    address_line2: str | None = None
    city: str
    state: str
    zip_code: str
    property_type: PropertyType = PropertyType.OFFICE
    square_footage: int = Field(gt=0)
    bathrooms: int = Field(ge=0, default=1)
    floors: int = Field(ge=1, default=1)
    access_notes: str | None = None


class PropertyOut(PropertyCreate):
    id: str
    customer_id: str
    full_address: str

    class Config:
        from_attributes = True


class CustomerCreate(BaseModel):
    company_name: str | None = None
    contact_name: str
    email: EmailStr
    phone: str
    billing_address: str | None = None
    notes: str | None = None


class CustomerUpdate(BaseModel):
    company_name: str | None = None
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    billing_address: str | None = None
    notes: str | None = None


class CustomerOut(BaseModel):
    id: str
    company_name: str | None
    contact_name: str
    email: str
    phone: str
    billing_address: str | None
    notes: str | None
    is_archived: bool
    created_at: datetime
    properties: list[PropertyOut] = []

    class Config:
        from_attributes = True


class CustomerListItem(BaseModel):
    id: str
    company_name: str | None
    contact_name: str
    email: str
    phone: str
    is_archived: bool
    created_at: datetime

    class Config:
        from_attributes = True
