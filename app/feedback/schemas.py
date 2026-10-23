from datetime import datetime
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class FeedbackOut(BaseModel):
    id: str
    job_id: str
    customer_id: str
    rating: int
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackSummary(BaseModel):
    average_rating: float | None
    review_count: int
    response_rate_percent: float
    recent: list[FeedbackOut]
