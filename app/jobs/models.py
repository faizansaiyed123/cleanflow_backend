from sqlalchemy import Column, String, Boolean, Integer, Enum, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import JobStatus, PhotoType


class Job(Base, UUIDPKMixin, TimestampMixin):
    """
    A single, independent unit of cleaning work on a specific date. Jobs
    are generated from a RecurringSchedule (or created manually / from a
    one-time quote) but once created they stand alone -- rescheduling or
    reassigning a job never depends on the schedule that spawned it, and
    changing that schedule never edits jobs that already exist.

    `version` implements optimistic concurrency control: every mutating
    endpoint that accepts an `expected_version` increments this counter
    and rejects the write (409) if the caller's expected_version is
    stale. This matters here specifically because job assignment and
    rescheduling are exactly the kind of action two managers can
    plausibly race on (both looking at the same unassigned job at once)
    -- without it, the second write silently overwrites the first with
    no indication either person did anything wrong.
    """

    __tablename__ = "jobs"

    version = Column(Integer, nullable=False, default=1)

    reference_number = Column(String(20), unique=True, nullable=False, index=True)

    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    property_id = Column(String(36), ForeignKey("properties.id"), nullable=False)
    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=True, index=True)
    schedule_id = Column(String(36), ForeignKey("recurring_schedules.id"), nullable=True)

    scheduled_start = Column(DateTime(), nullable=False, index=True)
    scheduled_end = Column(DateTime(), nullable=False)

    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.SCHEDULED, index=True)

    check_in_at = Column(DateTime(), nullable=True)
    check_in_lat = Column(String(30), nullable=True)
    check_in_lng = Column(String(30), nullable=True)
    check_out_at = Column(DateTime(), nullable=True)

    completed_at = Column(DateTime(), nullable=True)
    cancelled_at = Column(DateTime(), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    requires_photo_proof = Column(Boolean, default=True, nullable=False)

    customer = relationship("Customer")
    # Note: named "site" rather than "property" to avoid colliding with
    # Python's builtin @property decorator inside this class body.
    site = relationship("Property", back_populates="jobs")
    contract = relationship("Contract", back_populates="jobs")
    schedule = relationship("RecurringSchedule")

    assignments = relationship("JobAssignment", back_populates="job", cascade="all, delete-orphan")
    checklist_items = relationship("JobChecklistItem", back_populates="job", cascade="all, delete-orphan",
                                    order_by="JobChecklistItem.sort_order")
    photos = relationship("JobPhoto", back_populates="job", cascade="all, delete-orphan")
    job_notes = relationship("JobNote", back_populates="job", cascade="all, delete-orphan")
    invoice_items = relationship("InvoiceItem", back_populates="job")
    feedback = relationship("Feedback", back_populates="job", uselist=False)

    @property
    def actual_duration_minutes(self) -> int | None:
        if self.check_in_at and self.check_out_at:
            return int((self.check_out_at - self.check_in_at).total_seconds() // 60)
        return None


class JobAssignment(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "job_assignments"

    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=False, index=True)
    is_lead = Column(Boolean, default=True, nullable=False)

    job = relationship("Job", back_populates="assignments")
    employee = relationship("Employee", back_populates="assignments")


class JobChecklistItem(Base, UUIDPKMixin):
    """Copied from a ChecklistTemplate at job-creation time so later edits
    to the template never retroactively change an in-flight/completed job."""

    __tablename__ = "job_checklist_items"

    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
    label = Column(String(255), nullable=False)
    is_required = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime(), nullable=True)
    note = Column(String(500), nullable=True)

    job = relationship("Job", back_populates="checklist_items")


class JobPhoto(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "job_photos"

    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    uploaded_by_employee_id = Column(String(36), ForeignKey("employees.id"), nullable=True)
    photo_type = Column(Enum(PhotoType), nullable=False)
    storage_key = Column(String(500), nullable=False)  # path/key in object storage
    caption = Column(String(255), nullable=True)

    job = relationship("Job", back_populates="photos")


class JobNote(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "job_notes"

    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    author_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    body = Column(Text, nullable=False)
    is_problem_report = Column(Boolean, default=False, nullable=False)

    job = relationship("Job", back_populates="job_notes")
