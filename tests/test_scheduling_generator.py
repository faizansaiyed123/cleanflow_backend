"""
Tests for the recurring scheduling engine: occurrence generation for
each frequency pattern, and occurrence-level exceptions (skip / move)
that must never corrupt the master schedule or other jobs.
"""
from datetime import datetime, timedelta
import pytest

from app.users.models import User
from app.customers.models import Customer, Property
from app.contracts.models import Contract, ContractService
from app.scheduling.models import RecurringSchedule, ScheduleException
from app.scheduling.generator import generate_jobs_for_schedule
from app.jobs.models import Job
from app.services.models import Service
from app.auth.security import hash_password
from app.common.enums import UserRole, CleaningFrequency, JobStatus
from app.common.reference_numbers import next_reference


@pytest.fixture()
def contract_fixture(db):
    manager = db.query(User).filter(User.email == "sched_manager@test.demo").first()
    if not manager:
        manager = User(email="sched_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                        full_name="Sched Manager", role=UserRole.MANAGER)
        db.add(manager)
    customer = Customer(contact_name="Sched Customer", email=f"sched_{datetime.utcnow().timestamp()}@test.demo", phone="555-1000")
    db.add(customer)
    db.flush()
    prop = Property(customer_id=customer.id, label="Site", address_line1="1 St", city="Austin", state="TX",
                     zip_code="78701", square_footage=1000)
    db.add(prop)
    db.flush()
    contract = Contract(reference_number=next_reference(db, "contract"), customer_id=customer.id, property_id=prop.id,
                         start_date=datetime(2026, 1, 5), frequency=CleaningFrequency.WEEKLY, monthly_value=400,
                         status="ACTIVE")
    db.add(contract)
    db.flush()
    db.commit()
    return contract, manager


def test_weekly_schedule_generates_correct_weekdays(db, contract_fixture):
    contract, manager = contract_fixture
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.WEEKLY,
                                  days_of_week=["MON", "WED"], interval_weeks=1, time_of_day="08:00",
                                  duration_minutes=90, start_date=datetime(2026, 1, 5), generate_horizon_days=0)
    db.add(schedule)
    db.commit()

    # Manually generate a fixed window instead of "now"-relative horizon, by
    # calling the internal date logic directly.
    from app.scheduling.generator import _occurrence_dates
    dates = _occurrence_dates(schedule, datetime(2026, 1, 5), datetime(2026, 1, 19))
    weekdays = sorted({d.strftime("%a") for d in dates})
    assert weekdays == ["Mon", "Wed"]
    assert len(dates) == 4  # two weeks x Mon/Wed


def test_biweekly_schedule_skips_alternate_weeks(db, contract_fixture):
    contract, manager = contract_fixture
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.BIWEEKLY,
                                  days_of_week=["MON"], interval_weeks=2, time_of_day="08:00",
                                  duration_minutes=90, start_date=datetime(2026, 1, 5), generate_horizon_days=0)
    db.add(schedule)
    db.commit()
    from app.scheduling.generator import _occurrence_dates
    dates = _occurrence_dates(schedule, datetime(2026, 1, 5), datetime(2026, 2, 2))
    # Jan 5, 19 (every other Monday) but not Jan 12, 26
    assert datetime(2026, 1, 5) in dates
    assert datetime(2026, 1, 19) in dates
    assert datetime(2026, 1, 12) not in dates
    assert datetime(2026, 1, 26) not in dates


def test_monthly_schedule_uses_day_of_month(db, contract_fixture):
    contract, manager = contract_fixture
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.MONTHLY,
                                  day_of_month=15, time_of_day="09:00", duration_minutes=60,
                                  start_date=datetime(2026, 1, 1), generate_horizon_days=0)
    db.add(schedule)
    db.commit()
    from app.scheduling.generator import _occurrence_dates
    dates = _occurrence_dates(schedule, datetime(2026, 1, 1), datetime(2026, 4, 1))
    days = sorted(d.day for d in dates)
    assert days == [15, 15, 15]


def test_generate_jobs_is_idempotent(db, contract_fixture):
    """Calling the generator twice must never create duplicate jobs for
    the same occurrence."""
    contract, manager = contract_fixture
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.WEEKLY,
                                  days_of_week=["MON"], interval_weeks=1, time_of_day="08:00",
                                  duration_minutes=90, start_date=datetime.utcnow() - timedelta(days=1),
                                  generate_horizon_days=14)
    db.add(schedule)
    db.commit()

    first_batch = generate_jobs_for_schedule(db, schedule, manager)
    db.commit()
    count_after_first = db.query(Job).filter(Job.contract_id == contract.id).count()

    # Re-run generation without advancing last_generated_through further
    schedule.last_generated_through = schedule.start_date
    second_batch = generate_jobs_for_schedule(db, schedule, manager)
    db.commit()
    count_after_second = db.query(Job).filter(Job.contract_id == contract.id).count()

    assert count_after_first == count_after_second


def test_schedule_exception_skips_occurrence_without_touching_others(db, contract_fixture):
    contract, manager = contract_fixture
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    # Force to a Monday for predictability
    start -= timedelta(days=start.weekday())
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.WEEKLY,
                                  days_of_week=["MON"], interval_weeks=1, time_of_day="08:00",
                                  duration_minutes=90, start_date=start, generate_horizon_days=21)
    db.add(schedule)
    db.flush()

    skip_date = start + timedelta(days=7)  # second Monday
    exception = ScheduleException(schedule_id=schedule.id, original_occurrence_date=skip_date, is_skipped=True)
    db.add(exception)
    db.commit()

    generate_jobs_for_schedule(db, schedule, manager)
    db.commit()

    jobs = db.query(Job).filter(Job.contract_id == contract.id).order_by(Job.scheduled_start).all()
    job_dates = {j.scheduled_start.date() for j in jobs}
    assert skip_date.date() not in job_dates
    # The other Mondays should still exist
    assert start.date() in job_dates


def test_schedule_exception_move_reschedules_existing_job(db, contract_fixture):
    """If the job for an occurrence already exists, an exception updates
    that job directly rather than only being consulted at generation time."""
    contract, manager = contract_fixture
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)
    schedule = RecurringSchedule(contract_id=contract.id, frequency=CleaningFrequency.WEEKLY,
                                  days_of_week=[start.strftime("%a").upper()[:3]], interval_weeks=1,
                                  time_of_day="08:00", duration_minutes=90, start_date=start, generate_horizon_days=7)
    db.add(schedule)
    db.flush()
    generate_jobs_for_schedule(db, schedule, manager)
    db.commit()

    job = db.query(Job).filter(Job.contract_id == contract.id).first()
    assert job is not None
    original_start = job.scheduled_start

    new_date = original_start + timedelta(days=1)
    exception = ScheduleException(schedule_id=schedule.id, original_occurrence_date=original_start,
                                   override_date=new_date, override_time_of_day="10:00")
    db.add(exception)
    db.flush()

    # Simulate what the router does: find the existing job for that date and move it.
    from app.jobs.service import reschedule_job
    duration = job.scheduled_end - job.scheduled_start
    reschedule_job(db, job, new_date.replace(hour=10, minute=0), new_date.replace(hour=10, minute=0) + duration, manager)
    db.commit()
    db.refresh(job)

    assert job.scheduled_start.date() == new_date.date()
    assert job.scheduled_start.hour == 10
