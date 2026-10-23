"""
The background job runner. This is a real, independent execution
context (APScheduler running in-process background threads, each with
its own DB session) -- not just functions the request path happens to
call. It's what makes the outbox pattern actually asynchronous rather
than a decorative abstraction, and it's where all of CleanFlow's
"cron-like" work lives:

  - drain_outbox            every 3s   process pending domain events
  - drain_webhook_deliveries every 5s  attempt due webhook deliveries
  - generate_scheduled_jobs  every 60s catch up recurring job generation
  - sweep_overdue_and_expired every 60s flip stale quotes/invoices,
                                        fire contract-expiring events
  - refresh_analytics_rollup every 30s recompute the dashboard's
                                        materialized aggregate table

Every job pulls its own SessionLocal() and closes it when done, exactly
like a request handler would -- background jobs get the same isolation
guarantees request handlers do, just on a timer instead of an HTTP call.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.events.models import OutboxEvent
from app.events import handlers as event_handlers
from app.webhooks.models import WebhookDelivery
from app.webhooks.service import attempt_delivery
from app.observability.metrics import OUTBOX_PROCESSED, WEBHOOK_DELIVERIES

logger = logging.getLogger("cleanflow.worker")

_scheduler: BackgroundScheduler | None = None
BATCH_SIZE = 20


def drain_outbox():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        events = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.status.in_(["PENDING", "FAILED"]),
                    (OutboxEvent.next_attempt_at.is_(None)) | (OutboxEvent.next_attempt_at <= now))
            .order_by(OutboxEvent.created_at)
            .limit(BATCH_SIZE)
            .all()
        )
        for event in events:
            event.status = "PROCESSING"
            event.attempts += 1
            db.commit()
            try:
                payload = dict(event.payload or {})
                payload["_outbox_event_id"] = event.id
                event_handlers.dispatch(db, event.event_type, payload)
                event.status = "PROCESSED"
                event.processed_at = datetime.utcnow()
                OUTBOX_PROCESSED.labels(event_type=event.event_type, outcome="success").inc()
            except Exception as exc:  # noqa: BLE001 -- a bad event must never wedge the worker
                logger.exception("Failed processing outbox event %s (%s)", event.id, event.event_type)
                event.last_error = str(exc)[:500]
                if event.attempts >= event.max_attempts:
                    event.status = "DEAD_LETTER"
                else:
                    event.status = "FAILED"
                    event.next_attempt_at = datetime.utcnow() + timedelta(seconds=30 * event.attempts)
                OUTBOX_PROCESSED.labels(event_type=event.event_type, outcome="failure").inc()
            db.commit()
    finally:
        db.close()


def drain_webhook_deliveries():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        deliveries = (
            db.query(WebhookDelivery)
            .filter(WebhookDelivery.status.in_(["PENDING", "FAILED"]),
                    (WebhookDelivery.next_attempt_at.is_(None)) | (WebhookDelivery.next_attempt_at <= now))
            .order_by(WebhookDelivery.created_at)
            .limit(BATCH_SIZE)
            .all()
        )
        for delivery in deliveries:
            attempt_delivery(db, delivery)
            WEBHOOK_DELIVERIES.labels(status=delivery.status).inc()
            db.commit()
    finally:
        db.close()


def generate_scheduled_jobs():
    from app.scheduling.models import RecurringSchedule
    from app.scheduling.generator import generate_jobs_for_schedule

    db: Session = SessionLocal()
    try:
        schedules = db.query(RecurringSchedule).filter(RecurringSchedule.is_active.is_(True)).all()
        for schedule in schedules:
            try:
                generate_jobs_for_schedule(db, schedule, actor=None)
                db.commit()
            except Exception:
                logger.exception("Failed generating jobs for schedule %s", schedule.id)
                db.rollback()
    finally:
        db.close()


def sweep_overdue_and_expired():
    from app.invoices.service import refresh_overdue_status
    from app.quotes.service import expire_stale_quotes
    from app.contracts.models import Contract
    from app.common.enums import ContractStatus
    from app.events.bus import publish, EventType

    db: Session = SessionLocal()
    try:
        overdue_count = refresh_overdue_status(db)
        expired_count = expire_stale_quotes(db)

        soon = datetime.utcnow() + timedelta(days=7)
        expiring = db.query(Contract).filter(
            Contract.status == ContractStatus.ACTIVE, Contract.end_date.isnot(None),
            Contract.end_date <= soon, Contract.end_date >= datetime.utcnow(),
        ).all()
        for c in expiring:
            publish(db, EventType.CONTRACT_EXPIRING, {"contract_id": c.id, "reference_number": c.reference_number})

        db.commit()
        if overdue_count or expired_count or expiring:
            logger.info("Sweep: %d invoices overdue, %d quotes expired, %d contracts expiring soon",
                        overdue_count, expired_count, len(expiring))
    finally:
        db.close()


def refresh_search_index():
    from app.search.index import rebuild_index
    db: Session = SessionLocal()
    try:
        count = rebuild_index(db)
        logger.debug("Search index rebuilt: %d rows", count)
    finally:
        db.close()


def refresh_analytics_rollup():
    from app.reports.rollup import recompute_daily_metrics
    db: Session = SessionLocal()
    try:
        recompute_daily_metrics(db)
        db.commit()
    finally:
        db.close()


def start_background_worker() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(drain_outbox, "interval", seconds=3, id="drain_outbox")
    scheduler.add_job(drain_webhook_deliveries, "interval", seconds=5, id="drain_webhook_deliveries")
    scheduler.add_job(generate_scheduled_jobs, "interval", seconds=60, id="generate_scheduled_jobs")
    scheduler.add_job(sweep_overdue_and_expired, "interval", seconds=60, id="sweep_overdue_and_expired")
    scheduler.add_job(refresh_analytics_rollup, "interval", seconds=30, id="refresh_analytics_rollup")
    scheduler.add_job(refresh_search_index, "interval", seconds=10, id="refresh_search_index")
    scheduler.start()
    _scheduler = scheduler
    logger.info("Background worker started (outbox, webhooks, scheduling, sweeps, analytics rollup)")
    return scheduler


def stop_background_worker():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
