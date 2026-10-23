from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import get_current_user, require_staff
from app.users.models import User
from app.common.enums import UserRole, JobStatus
from app.common.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.audit.service import record_audit
from app.jobs.models import Job
from app.feedback.models import Feedback
from app.feedback.schemas import FeedbackCreate, FeedbackOut, FeedbackSummary
from app.notifications.service import notify_role
from app.events.bus import publish, EventType

router = APIRouter(tags=["feedback"])


@router.post("/api/jobs/{job_id}/feedback", response_model=FeedbackOut, status_code=201)
def submit_feedback(job_id: str, payload: FeedbackCreate, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.CUSTOMER:
        raise ForbiddenError("Only the customer can submit feedback for their own job")
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise NotFoundError("Job", job_id)
    if job.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this job")
    if job.status != JobStatus.COMPLETED:
        raise ConflictError("Feedback can only be submitted for a completed job")
    if job.feedback:
        raise ConflictError("Feedback has already been submitted for this job")

    feedback = Feedback(job_id=job_id, customer_id=current_user.customer_id, rating=payload.rating,
                         comment=payload.comment)
    db.add(feedback)
    db.flush()
    record_audit(db, current_user, "feedback.submitted", "Feedback", feedback.id, new_state={"rating": payload.rating})
    publish(db, EventType.FEEDBACK_RECEIVED, {
        "feedback_id": feedback.id, "rating": payload.rating, "comment": payload.comment,
    })
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/api/feedback", response_model=FeedbackSummary)
def feedback_summary(db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    from sqlalchemy import func

    # Aggregate (count, avg) in SQL, and only pull the 10 rows we
    # actually display -- not the entire feedback table just to count it.
    review_count, avg = db.query(func.count(Feedback.id), func.avg(Feedback.rating)).first()
    completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED).count()
    avg_rating = round(avg, 2) if avg is not None else None
    response_rate = round((review_count / completed_jobs) * 100, 1) if completed_jobs else 0.0
    recent = db.query(Feedback).order_by(Feedback.created_at.desc()).limit(10).all()
    return FeedbackSummary(average_rating=avg_rating, review_count=review_count or 0,
                            response_rate_percent=response_rate, recent=recent)
