from datetime import datetime
from pydantic import BaseModel, Field

from app.common.enums import PaymentMethod


class PaymentCreate(BaseModel):
    amount: float = Field(gt=0)
    method: PaymentMethod
    paid_at: datetime | None = None
    reference: str | None = None
    notes: str | None = None
    allow_overpayment: bool = False


class PaymentOut(BaseModel):
    id: str
    invoice_id: str
    amount: float
    method: PaymentMethod
    paid_at: datetime
    reference: str | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True
