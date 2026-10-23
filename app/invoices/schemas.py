from datetime import datetime
from pydantic import BaseModel, Field

from app.common.enums import InvoiceStatus, InvoiceSourceType


class InvoiceLineItemIn(BaseModel):
    description: str
    amount: float
    job_id: str | None = None


class ManualInvoiceCreate(BaseModel):
    customer_id: str
    property_id: str | None = None
    contract_id: str | None = None
    items: list[InvoiceLineItemIn]
    discount_amount: float = 0.0
    tax_rate_percent: float = 0.0
    due_in_days: int = 15
    notes: str | None = None


class InvoiceFromJobRequest(BaseModel):
    due_in_days: int = 15
    tax_rate_percent: float = 0.0


class InvoiceItemOut(BaseModel):
    id: str
    description: str
    amount: float
    job_id: str | None

    class Config:
        from_attributes = True


class InvoiceOut(BaseModel):
    id: str
    reference_number: str
    customer_id: str
    property_id: str | None
    contract_id: str | None
    source_type: InvoiceSourceType
    subtotal: float
    discount_amount: float
    tax_amount: float
    total: float
    amount_paid: float
    balance_due: float
    status: InvoiceStatus
    due_date: datetime
    sent_at: datetime | None
    notes: str | None
    created_at: datetime
    items: list[InvoiceItemOut] = []

    class Config:
        from_attributes = True
