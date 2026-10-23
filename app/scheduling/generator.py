"""
The recurring scheduling engine.

Core guarantee: generate_jobs_for_schedule() only ever CREATES new Job
rows for occurrences that don't have one yet (tracked via
schedule.last_generated_through). It never edits an existing Job. This
is what makes "recurring schedule changes don't corrupt historical
jobs" true by construction rather than by convention -- there is
simply no code path that goes back and rewrites a Job from its
schedule.

Occurrence-level overrides (ScheduleException) are consulted only for
occurrences being generated for the first time: if an exception marks a
date skipped, no Job is created for it; if an exception moves a date/
time, the Job is created at the overridden date/time instead of the
schedule's default pattern.
"""
from datetime import datetime, timedelta, time

from sqlalchemy.orm import Session

from app.common.enums import CleaningFrequency, JobStatus
from app.common.reference_numbers import next_reference
from app.scheduling.models import RecurringSchedule, ScheduleException
from app.contracts.models import Contract, ContractService
from app.jobs.models import Job, JobChecklistItem
from app.services.models import Service

WEEKDAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _parse_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _occurrence_dates(schedule: RecurringSchedule, window_start: datetime, window_end: datetime) -> list[datetime]:
    """Compute the calendar dates (not yet times) this schedule's pattern
    falls on within [window_start, window_end)."""
    dates = []
    cursor = max(schedule.start_date, window_start)
    cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
    end = min(schedule.end_date, window_end) if schedule.end_date else window_end

    if schedule.frequency == CleaningFrequency.MONTHLY:
        dom = schedule.day_of_month or 1
        month_cursor = cursor.replace(day=1)
        while month_cursor < end:
            try:
                candidate = month_cursor.replace(day=dom)
            except ValueError:
                month_cursor = _add_month(month_cursor)
                continue
            if window_start <= candidate < end and candidate >= schedule.start_date:
                dates.append(candidate)
            month_cursor = _add_month(month_cursor)
        return dates

    # DAILY, WEEKLY, BIWEEKLY, CUSTOM all reduce to "which weekdays, every
    # N weeks, starting from schedule.start_date's week".
    days = schedule.days_of_week or (WEEKDAY_CODES[:5] if schedule.frequency == CleaningFrequency.DAILY else ["MON"])
    interval = schedule.interval_weeks or 1
    anchor_week_start = schedule.start_date - timedelta(days=schedule.start_date.weekday())

    day = cursor
    while day < end:
        if day >= schedule.start_date:
            code = WEEKDAY_CODES[day.weekday()]
            if code in days:
                weeks_since_anchor = (day - anchor_week_start).days // 7
                if weeks_since_anchor % interval == 0:
                    dates.append(day)
        day += timedelta(days=1)
    return dates


def _add_month(dt: datetime) -> datetime:
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def generate_jobs_for_schedule(db: Session, schedule: RecurringSchedule, actor=None) -> list[Job]:
    """Generate any not-yet-created Job occurrences from
    schedule.last_generated_through (or schedule.start_date) out to
    schedule.generate_horizon_days from today. Safe to call repeatedly
    (e.g. from a daily cron) -- it is a no-op once fully caught up."""
    now = datetime.now(schedule.start_date.tzinfo)
    window_start = schedule.last_generated_through or schedule.start_date
    horizon = now + timedelta(days=schedule.generate_horizon_days)
    window_end = min(horizon, schedule.end_date) if schedule.end_date else horizon

    if window_end <= window_start:
        return []

    contract: Contract = schedule.contract
    exceptions = {
        exc.original_occurrence_date.date(): exc
        for exc in db.query(ScheduleException).filter(ScheduleException.schedule_id == schedule.id).all()
    }

    checklist_source = _resolve_checklist_items(db, contract)
    default_hhmm = _parse_time(schedule.time_of_day)

    created: list[Job] = []
    for occ_date in _occurrence_dates(schedule, window_start, window_end):
        exc = exceptions.get(occ_date.date())
        if exc and exc.is_skipped:
            continue

        effective_date = exc.override_date if (exc and exc.override_date) else occ_date
        effective_time = _parse_time(exc.override_time_of_day) if (exc and exc.override_time_of_day) else default_hhmm

        scheduled_start = effective_date.replace(
            hour=effective_time.hour, minute=effective_time.minute, second=0, microsecond=0
        )
        scheduled_end = scheduled_start + timedelta(minutes=schedule.duration_minutes)

        # Idempotency guard: never double-create a job already sitting at
        # this exact start time for this contract.
        exists = (
            db.query(Job)
            .filter(Job.contract_id == contract.id, Job.scheduled_start == scheduled_start)
            .first()
        )
        if exists:
            continue

        job = Job(
            reference_number=next_reference(db, "job"),
            customer_id=contract.customer_id,
            property_id=contract.property_id,
            contract_id=contract.id,
            schedule_id=schedule.id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status=JobStatus.SCHEDULED,
        )
        db.add(job)
        db.flush()
        for item in checklist_source:
            db.add(JobChecklistItem(
                job_id=job.id, label=item["label"], is_required=item["is_required"], sort_order=item["sort_order"],
            ))
        created.append(job)

    schedule.last_generated_through = window_end
    return created


def _resolve_checklist_items(db: Session, contract: Contract) -> list[dict]:
    """Use the checklist template of the contract's primary (first)
    service, if one is configured; otherwise fall back to a sensible
    generic commercial-cleaning checklist so every job still has one."""
    contract_service: ContractService | None = contract.services[0] if contract.services else None
    if contract_service:
        service = db.query(Service).filter(Service.id == contract_service.service_id).first()
        if service and service.checklist_template:
            return [
                {"label": i.label, "is_required": i.is_required, "sort_order": i.sort_order}
                for i in service.checklist_template.items
            ]
    return [
        {"label": "Empty trash bins", "is_required": True, "sort_order": 0},
        {"label": "Vacuum/sweep floors", "is_required": True, "sort_order": 1},
        {"label": "Clean and disinfect restrooms", "is_required": True, "sort_order": 2},
        {"label": "Wipe down surfaces and desks", "is_required": True, "sort_order": 3},
        {"label": "Restock supplies", "is_required": False, "sort_order": 4},
        {"label": "Clean common areas", "is_required": True, "sort_order": 5},
    ]
