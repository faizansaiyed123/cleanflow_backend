from pydantic import BaseModel


class CompanySettingUpdate(BaseModel):
    company_name: str | None = None
    logo_url: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    business_hours: dict | None = None
    currency: str | None = None
    default_tax_rate_percent: float | None = None
    invoice_due_days: float | None = None
    quote_validity_days: float | None = None
    notification_settings: dict | None = None


class CompanySettingOut(BaseModel):
    id: str
    company_name: str
    logo_url: str | None
    phone: str | None
    email: str | None
    address: str | None
    business_hours: dict
    currency: str
    default_tax_rate_percent: float
    invoice_due_days: float
    quote_validity_days: float
    notification_settings: dict

    class Config:
        from_attributes = True
