from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import get_current_user
from app.users.models import User
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ForbiddenError
from app.jobs.models import JobPhoto, Job
from app.uploads.storage import read_file

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/job-photos/{photo_id}")
def get_job_photo(photo_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Serves job photos behind auth, enforcing the same customer/employee
    scoping as the rest of the API rather than exposing a public static
    file URL. A production deployment would instead issue short-lived
    signed URLs against S3/GCS; this endpoint plays the same access-
    control role for the local-disk demo backend."""
    photo = db.query(JobPhoto).filter(JobPhoto.id == photo_id).first()
    if not photo:
        raise NotFoundError("Photo", photo_id)
    job = db.query(Job).filter(Job.id == photo.job_id).first()
    if current_user.role == UserRole.CUSTOMER and job.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this photo")
    data = read_file(photo.storage_key)
    ext = photo.storage_key.rsplit(".", 1)[-1]
    media_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
    return Response(content=data, media_type=media_type)
