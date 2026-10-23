from sqlalchemy import Column, String, Integer, Boolean, Enum, ForeignKey, DateTime, JSON, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import CleaningFrequency


class RecurringSchedule(Base, UUIDPKMixin, TimestampMixin):
    """
    The *master pattern* for a contract, e.g. "every Mon/Wed/Fri at 8:00
    AM" or "every second Tuesday". This row is a template only -- it
    generates independent Job rows (see app/scheduling/generator.py).
    Editing this pattern later changes what gets generated going
    forward; it never reaches back and edits jobs already created.
    """

    __tablename__ = "recurring_schedules"

    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=False, unique=True)

    frequency = Column(Enum(CleaningFrequency), nullable=False)
    # Days of week this applies to, e.g. ["MON", "WED", "FRI"]. Used for
    # WEEKLY/BIWEEKLY/CUSTOM. Ignored for DAILY/MONTHLY.
    days_of_week = Column(JSON, nullable=False, default=list)
    # For BIWEEKLY/CUSTOM interval patterns: repeat every N weeks.
    interval_weeks = Column(Integer, nullable=False, default=1)
    # For MONTHLY: day-of-month to run on (1-28 to stay valid every month).
    day_of_month = Column(Integer, nullable=True)

    time_of_day = Column(String(5), nullable=False, default="08:00")  # "HH:MM"
    duration_minutes = Column(Integer, nullable=False, default=90)

    start_date = Column(DateTime(), nullable=False)
    end_date = Column(DateTime(), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # How far ahead we keep jobs generated (rolling horizon).
    generate_horizon_days = Column(Integer, nullable=False, default=30)
    last_generated_through = Column(DateTime(), nullable=True)

    contract = relationship("Contract", back_populates="schedule")
    exceptions = relationship("ScheduleException", back_populates="schedule", cascade="all, delete-orphan")


class ScheduleException(Base, UUIDPKMixin, TimestampMixin):
    """
    A one-off override for a single occurrence of a RecurringSchedule,
    e.g. "the Monday 8/12 cleaning moves to Tuesday 8/13 at 10:00" or
    "skip the occurrence on 12/25". Consulted only at job-generation time
    for occurrences that don't have a Job yet; it never mutates jobs
    that already exist (reschedule an existing job directly instead via
    the Jobs API).
    """

    __tablename__ = "schedule_exceptions"

    schedule_id = Column(String(36), ForeignKey("recurring_schedules.id"), nullable=False)

    original_occurrence_date = Column(DateTime(), nullable=False)
    is_skipped = Column(Boolean, default=False, nullable=False)
    override_date = Column(DateTime(), nullable=True)
    override_time_of_day = Column(String(5), nullable=True)
    note = Column(Text, nullable=True)

    schedule = relationship("RecurringSchedule", back_populates="exceptions")
