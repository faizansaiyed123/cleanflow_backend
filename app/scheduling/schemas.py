from datetime import datetime
from pydantic import BaseModel

from app.common.enums import CleaningFrequency


class RecurringScheduleOut(BaseModel):
    id: str
    contract_id: str
    frequency: CleaningFrequency
    days_of_week: list[str]
    interval_weeks: int
    day_of_month: int | None
    time_of_day: str
    duration_minutes: int
    start_date: datetime
    end_date: datetime | None
    is_active: bool
    generate_horizon_days: int
    last_generated_through: datetime | None

    class Config:
        from_attributes = True


class RecurringScheduleUpdate(BaseModel):
    days_of_week: list[str] | None = None
    interval_weeks: int | None = None
    day_of_month: int | None = None
    time_of_day: str | None = None
    duration_minutes: int | None = None
    end_date: datetime | None = None
    generate_horizon_days: int | None = None


class ScheduleExceptionCreate(BaseModel):
    original_occurrence_date: datetime
    is_skipped: bool = False
    override_date: datetime | None = None
    override_time_of_day: str | None = None
    note: str | None = None


class ScheduleExceptionOut(ScheduleExceptionCreate):
    id: str
    schedule_id: str

    class Config:
        from_attributes = True
