"""
CleanFlow API entrypoint. Wires together every domain router, sets up
CORS, global exception handling (no internal stack traces ever reach
the client), and creates the database schema on startup.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import get_settings
from app.config.database import Base, engine, get_db, SessionLocal
import app.config.model_registry  # noqa: F401 -- registers all tables

from app.common.exceptions import AppError
from app.observability.logging_setup import configure_logging
from app.observability.middleware import ObservabilityMiddleware
from app.events.worker import start_background_worker, stop_background_worker
from app.feature_flags.service import ensure_defaults as ensure_default_feature_flags

from app.auth.router import router as auth_router
from app.users.router import router as users_router
from app.customers.router import router as customers_router
from app.employees.router import router as employees_router
from app.leads.router import router as leads_router
from app.services.router import router as services_router
from app.pricing.router import router as pricing_router
from app.quotes.router import router as quotes_router
from app.contracts.router import router as contracts_router
from app.scheduling.router import router as scheduling_router
from app.jobs.router import router as jobs_router
from app.invoices.router import router as invoices_router
from app.payments.router import router as payments_router
from app.feedback.router import router as feedback_router
from app.notifications.router import router as notifications_router
from app.audit.router import router as audit_router
from app.config.router import router as settings_router
from app.reports.router import router as reports_router
from app.uploads.router import router as uploads_router
from app.webhooks.router import router as webhooks_router
from app.feature_flags.router import router as feature_flags_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanflow")
configure_logging()

settings = get_settings()

app = FastAPI(
    title="CleanFlow API",
    description="Commercial Cleaning Operations Management Platform",
    version="1.0.0",
)

app.add_middleware(ObservabilityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces / internals to the client.
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Please try again."})


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_feature_flags(db)
        db.commit()
        from app.search.index import rebuild_index
        rebuild_index(db)
    finally:
        db.close()
    if not settings.disable_background_worker:
        start_background_worker()


@app.on_event("shutdown")
def on_shutdown():
    stop_background_worker()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/health/ready")
def readiness():
    """Kubernetes-style readiness probe: distinct from liveness (`/api/health`,
    'is the process up') -- this checks 'can the process actually serve a
    real request right now', i.e. can it reach its database. A load
    balancer should stop routing traffic here on failure without
    necessarily restarting the pod, which is exactly the distinction
    liveness vs readiness probes exist to make."""
    from sqlalchemy import text
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": str(exc)[:200]})


@app.get("/metrics")
def metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response as StarletteResponse
    return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


for r in [
    auth_router, users_router, customers_router, employees_router, leads_router, services_router,
    pricing_router, quotes_router, contracts_router, scheduling_router, jobs_router, invoices_router,
    payments_router, feedback_router, notifications_router, audit_router, settings_router, reports_router,
    uploads_router, webhooks_router, feature_flags_router,
]:
    app.include_router(r)
