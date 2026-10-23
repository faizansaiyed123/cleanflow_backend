from datetime import datetime
from pydantic import BaseModel

from app.common.enums import ContractStatus, CleaningFrequency


class ContractOut(BaseModel):
    id: str
    reference_number: str
    customer_id: str
    property_id: str
    originating_quote_id: str | None
    start_date: datetime
    end_date: datetime | None
    frequency: CleaningFrequency
    monthly_value: float
    terms: str | None
    notes: str | None
    status: ContractStatus
    paused_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    renewed_from_contract_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ContractCancelRequest(BaseModel):
    reason: str


class ContractRenewRequest(BaseModel):
    new_end_date: datetime | None = None


class ContractHealthOut(BaseModel):
    contract_id: str
    status: ContractStatus
    is_expiring_soon: bool
    days_until_expiration: int | None
    completed_job_count: int
    cancelled_or_noshow_job_count: int
    job_completion_rate: float | None
    total_revenue_invoiced: float
    outstanding_invoice_total: float
    average_feedback_rating: float | None
