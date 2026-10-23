from datetime import datetime
from pydantic import BaseModel

from app.common.enums import JobStatus, PhotoType


class JobAssignRequest(BaseModel):
    employee_ids: list[str]
    expected_version: int | None = None


class JobRescheduleRequest(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime
    expected_version: int | None = None


class JobCancelRequest(BaseModel):
    reason: str
    expected_version: int | None = None


class CheckInRequest(BaseModel):
    lat: str | None = None
    lng: str | None = None


class ChecklistItemToggleRequest(BaseModel):
    is_completed: bool
    note: str | None = None


class JobNoteCreate(BaseModel):
    body: str
    is_problem_report: bool = False


class ChecklistItemOut(BaseModel):
    id: str
    label: str
    is_required: bool
    sort_order: int
    is_completed: bool
    completed_at: datetime | None
    note: str | None

    class Config:
        from_attributes = True


class JobPhotoOut(BaseModel):
    id: str
    photo_type: PhotoType
    caption: str | None
    created_at: datetime
    uploaded_by_employee_id: str | None

    class Config:
        from_attributes = True


class JobNoteOut(BaseModel):
    id: str
    body: str
    is_problem_report: bool
    created_at: datetime
    author_user_id: str | None

    class Config:
        from_attributes = True


class JobAssignmentOut(BaseModel):
    employee_id: str
    employee_name: str
    is_lead: bool


class JobOut(BaseModel):
    id: str
    reference_number: str
    version: int
    customer_id: str
    property_id: str
    contract_id: str | None
    scheduled_start: datetime
    scheduled_end: datetime
    status: JobStatus
    check_in_at: datetime | None
    check_out_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    requires_photo_proof: bool
    actual_duration_minutes: int | None = None
    customer_name: str | None = None
    property_label: str | None = None
    property_address: str | None = None
    assignments: list[JobAssignmentOut] = []
    checklist_items: list[ChecklistItemOut] = []
    photos: list[JobPhotoOut] = []
    job_notes: list[JobNoteOut] = []

    class Config:
        from_attributes = True


class JobListItem(BaseModel):
    id: str
    reference_number: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: JobStatus
    customer_name: str | None = None
    property_label: str | None = None

    class Config:
        from_attributes = True
