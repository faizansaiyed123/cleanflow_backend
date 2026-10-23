"""
Contract lifecycle logic, including the quote -> contract -> schedule ->
jobs automation that fires when a quote is accepted.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.common.enums import ContractStatus, CleaningFrequency, QuoteStatus
from app.common.exceptions import ConflictError, ValidationAppError
from app.common.reference_numbers import next_reference
from app.audit.service import record_audit
from app.contracts.models import Contract, ContractService
from app.scheduling.models import RecurringSchedule
from app.scheduling.generator import generate_jobs_for_schedule
from app.quotes.models import Quote
from app.jobs.models import Job, JobChecklistItem
from app.users.models import User

# Approximate visits/month used only to express a recurring contract's
# per-visit price as a "monthly value" figure for reporting; billing
# itself is always driven by actual completed jobs, not this estimate.
VISITS_PER_MONTH = {
    CleaningFrequency.DAILY: 21.7,
    CleaningFrequency.WEEKLY: 4.33,
    CleaningFrequency.BIWEEKLY: 2.17,
    CleaningFrequency.MONTHLY: 1.0,
    CleaningFrequency.CUSTOM: 4.33,
    CleaningFrequency.ONE_TIME: 0.0,
}

DEFAULT_DAYS_OF_WEEK = {
    CleaningFrequency.DAILY: ["MON", "TUE", "WED", "THU", "FRI"],
    CleaningFrequency.WEEKLY: ["MON"],
    CleaningFrequency.BIWEEKLY: ["MON"],
    CleaningFrequency.CUSTOM: ["MON", "WED", "FRI"],
}


def activate_contract_from_accepted_quote(db: Session, quote: Quote, actor: User | None) -> Contract:
    """
    Transactional, idempotent quote-acceptance workflow:
      1. If this quote already has a contract (unique FK), return it --
         accepting an already-accepted quote can never create a duplicate.
      2. Otherwise create Contract + ContractService rows from the quote.
      3. For recurring frequencies, create a RecurringSchedule and
         immediately generate the first horizon of Jobs.
      4. For ONE_TIME, skip the schedule and create a single Job.
    The caller is responsible for wrapping this in a single db.commit()
    so steps 2-4 either all land or none do.
    """
    if quote.contract:
        return quote.contract

    if quote.status != QuoteStatus.ACCEPTED:
        raise ConflictError("Quote must be ACCEPTED before a contract can be created")

    reference = next_reference(db, "contract")
    start_date = datetime.utcnow() + timedelta(days=2)
    monthly_value = round(quote.total * VISITS_PER_MONTH.get(quote.frequency, 4.33), 2)

    contract = Contract(
        reference_number=reference,
        customer_id=quote.customer_id,
        property_id=quote.property_id,
        originating_quote_id=quote.id,
        start_date=start_date,
        frequency=quote.frequency,
        monthly_value=monthly_value,
        terms=quote.terms,
        status=ContractStatus.ACTIVE,
    )
    db.add(contract)
    db.flush()

    for item in quote.items:
        db.add(ContractService(contract_id=contract.id, service_id=item.service_id, price=item.amount))

    record_audit(db, actor, "contract.created", "Contract", contract.id, new_state={"from_quote": quote.id})

    if quote.frequency == CleaningFrequency.ONE_TIME:
        from app.common.reference_numbers import next_reference as _next_ref
        job = Job(
            reference_number=_next_ref(db, "job"),
            customer_id=contract.customer_id,
            property_id=contract.property_id,
            contract_id=contract.id,
            scheduled_start=start_date,
            scheduled_end=start_date + timedelta(minutes=90),
        )
        db.add(job)
        db.flush()
        for label in ["Empty trash bins", "Vacuum/sweep floors", "Clean and disinfect restrooms", "Wipe down surfaces"]:
            db.add(JobChecklistItem(job_id=job.id, label=label, is_required=True))
    else:
        days_of_week = DEFAULT_DAYS_OF_WEEK.get(quote.frequency, ["MON"])
        interval = 2 if quote.frequency == CleaningFrequency.BIWEEKLY else 1
        schedule = RecurringSchedule(
            contract_id=contract.id,
            frequency=quote.frequency,
            days_of_week=days_of_week,
            interval_weeks=interval,
            time_of_day="08:00",
            duration_minutes=90,
            start_date=start_date,
        )
        db.add(schedule)
        db.flush()
        generate_jobs_for_schedule(db, schedule, actor)

    return contract


def cancel_contract(db: Session, contract: Contract, reason: str, actor: User) -> Contract:
    if contract.status == ContractStatus.CANCELLED:
        raise ConflictError("Contract is already cancelled")
    previous = {"status": contract.status.value}
    contract.status = ContractStatus.CANCELLED
    contract.cancelled_at = datetime.utcnow()
    contract.cancellation_reason = reason
    if contract.schedule:
        contract.schedule.is_active = False
    # Future scheduled jobs that haven't happened yet should not silently
    # remain on the calendar for a cancelled contract.
    from app.common.enums import JobStatus
    future_jobs = (
        db.query(Job)
        .filter(Job.contract_id == contract.id, Job.status.in_([JobStatus.SCHEDULED, JobStatus.ASSIGNED]),
                Job.scheduled_start > datetime.utcnow())
        .all()
    )
    for job in future_jobs:
        job.status = JobStatus.CANCELLED
        job.cancellation_reason = f"Contract cancelled: {reason}"
        job.cancelled_at = datetime.utcnow()
    record_audit(db, actor, "contract.cancelled", "Contract", contract.id, previous_state=previous,
                 new_state={"status": "CANCELLED", "reason": reason})
    return contract


def pause_contract(db: Session, contract: Contract, actor: User) -> Contract:
    if contract.status != ContractStatus.ACTIVE:
        raise ConflictError("Only an active contract can be paused")
    contract.status = ContractStatus.PAUSED
    contract.paused_at = datetime.utcnow()
    if contract.schedule:
        contract.schedule.is_active = False
    record_audit(db, actor, "contract.paused", "Contract", contract.id)
    return contract


def resume_contract(db: Session, contract: Contract, actor: User) -> Contract:
    if contract.status != ContractStatus.PAUSED:
        raise ConflictError("Only a paused contract can be resumed")
    contract.status = ContractStatus.ACTIVE
    contract.paused_at = None
    if contract.schedule:
        contract.schedule.is_active = True
        # Resume generation from "now" rather than backfilling the paused
        # window with jobs that were never actually going to happen.
        contract.schedule.last_generated_through = datetime.utcnow()
        generate_jobs_for_schedule(db, contract.schedule, actor)
    record_audit(db, actor, "contract.resumed", "Contract", contract.id)
    return contract


def renew_contract(db: Session, contract: Contract, new_end_date, actor: User) -> Contract:
    if contract.status not in (ContractStatus.ACTIVE, ContractStatus.EXPIRED):
        raise ConflictError("Only an active or expired contract can be renewed")
    reference = next_reference(db, "contract")
    renewed = Contract(
        reference_number=reference,
        customer_id=contract.customer_id,
        property_id=contract.property_id,
        start_date=max(contract.end_date or datetime.utcnow(), datetime.utcnow()),
        end_date=new_end_date,
        frequency=contract.frequency,
        monthly_value=contract.monthly_value,
        terms=contract.terms,
        status=ContractStatus.ACTIVE,
        renewed_from_contract_id=contract.id,
    )
    db.add(renewed)
    db.flush()
    for cs in contract.services:
        db.add(ContractService(contract_id=renewed.id, service_id=cs.service_id, price=cs.price))
    if contract.schedule:
        schedule = RecurringSchedule(
            contract_id=renewed.id,
            frequency=contract.schedule.frequency,
            days_of_week=contract.schedule.days_of_week,
            interval_weeks=contract.schedule.interval_weeks,
            day_of_month=contract.schedule.day_of_month,
            time_of_day=contract.schedule.time_of_day,
            duration_minutes=contract.schedule.duration_minutes,
            start_date=renewed.start_date,
            end_date=new_end_date,
        )
        db.add(schedule)
        db.flush()
        generate_jobs_for_schedule(db, schedule, actor)
    contract.status = ContractStatus.EXPIRED
    record_audit(db, actor, "contract.renewed", "Contract", contract.id, new_state={"renewed_as": renewed.id})
    return renewed
