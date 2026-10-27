# CleanFlow Backend

CleanFlow Backend is the FastAPI service for a commercial cleaning operations platform. It connects customer inquiries and quote management with contracts, recurring schedules, field jobs, invoicing, payments, and customer history. The application uses SQLAlchemy for persistence and separates functionality into domain-specific modules.

**Product walkthrough:** [Read the CleanFlow Product Walkthrough](https://github.com/faizansaiyed123/cleanflow_frontend/blob/main/docs/testing/VISUAL-TEST-WALKTHROUGH.md)

Related screenshots: [Home](https://github.com/faizansaiyed123/cleanflow_frontend/blob/main/docs/testing/visuals/01-home.png) · [Request a Quote](https://github.com/faizansaiyed123/cleanflow_frontend/blob/main/docs/testing/visuals/02-request-quote.png) · [Login](https://github.com/faizansaiyed123/cleanflow_frontend/blob/main/docs/testing/visuals/03-login.png)

## Key Features

- **Authentication and access control:** JWT-based login, password hashing, role-based permissions, and customer-record access checks.
- **Customer intake and CRM:** Public quote requests, lead management, customer and property records, employee records, and service catalogs.
- **Quotes and contracts:** Pricing previews, quote creation and lifecycle actions, PDF exports, contract management, and contract health summaries.
- **Scheduling and field operations:** Recurring schedules, calendar queries, employee assignment, job check-in/check-out, checklists, notes, photo uploads, and completion requirements.
- **Billing and customer feedback:** Invoice generation and management, invoice PDFs and CSV exports, payment recording, payment idempotency, and feedback collection.
- **Administration and reporting:** Dashboard summaries, analytics, customer timelines, search, audit logs, settings, notifications, and feature flags.
- **Background processing and integrations:** Event-outbox processing, scheduled-job generation, webhook delivery with request signing and retry handling, and periodic reporting and search-index refreshes.
- **Operational endpoints:** Health checks, a database readiness check, rate limiting on selected endpoints, and Prometheus metrics.

## Tech Stack and Architecture

- **API:** FastAPI 0.115.0 and Uvicorn 0.30.6.
- **Data layer:** SQLAlchemy 2.0.35, Pydantic 2.9.2, and Pydantic Settings 2.5.2. SQLite is the configured default database.
- **Authentication:** `python-jose` for JWT handling and Passlib with bcrypt for password hashing.
- **Schema management:** Alembic 1.13.3, with an initial schema migration. Application startup also calls SQLAlchemy's `create_all`.
- **Background jobs:** APScheduler 3.10.4 and an application event outbox.
- **Operational tooling:** Prometheus Client 0.21.0 for metrics and ReportLab 4.2.5 for PDF generation.
- **Testing:** pytest 8.3.3, HTTPX, and Respx.

The application entry point is `app/main.py`. Domain modules contain routers and, where applicable, models, schemas, and service functions. Authentication dependencies enforce the permissions declared by protected endpoints.

## Companion Repository

The React/Vite frontend is maintained separately:

- [CleanFlow Frontend](https://github.com/faizansaiyed123/cleanflow_frontend)

## Quick Start

Prerequisites: Python and pip. The repository does not declare a specific Python version.

From the repository root, create a virtual environment and install the dependencies:

```bash
python -m venv .venv
pip install -r requirements.txt
```

Activate the virtual environment using the command appropriate for your shell, then start the API:

```bash
uvicorn app.main:app --reload
```

FastAPI's interactive API documentation is available at `/docs`, and its alternative documentation interface is available at `/redoc`.

### Database Migrations

The repository includes an Alembic migration. To apply the migration:

```bash
alembic upgrade head
```

The Alembic configuration obtains its database URL from the application settings.

### Optional Demo Data

The repository includes `seed.py`:

```bash
python seed.py
```

**Warning:** This script drops and recreates the application's database tables before inserting demo data. Use it only with a disposable database whose existing data can be deleted.

## Environment Variables

The repository does not contain a `.env.example`. The following names are derived from the environment-backed settings in `app/config/settings.py`. Names only; no values are provided here.

- `APP_NAME`
- `ENVIRONMENT`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `UPLOAD_ROOT`
- `MAX_UPLOAD_SIZE_MB`
- `ALLOWED_IMAGE_TYPES`
- `DEFAULT_CURRENCY`
- `DEFAULT_TAX_RATE_PERCENT`
- `QUOTE_DEFAULT_VALIDITY_DAYS`
- `CORS_ORIGINS`
- `DISABLE_BACKGROUND_WORKER`

## Tests

Install the dependencies, then run the test suite from the repository root:

```bash
pytest
```

The test configuration uses a temporary SQLite database and disables the background worker during tests. The test files cover authorization and data isolation, quote and contract workflows, scheduling, job completion requirements, pricing, payments, idempotency, exports, search, webhooks, and feature flags.

## Project Structure

```text
cleanflow_backend/
├── app/
│   ├── main.py
│   ├── auth/ users/ customers/ employees/
│   ├── leads/ services/ pricing/ quotes/ contracts/
│   ├── scheduling/ jobs/ invoices/ payments/
│   ├── feedback/ notifications/ audit/ config/
│   ├── feature_flags/ events/ webhooks/ idempotency/
│   ├── search/ reports/ observability/
│   ├── uploads/ pdf_export/ common/
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── conftest.py
│   └── test_*.py
├── requirements.txt
├── pytest.ini
├── alembic.ini
└── seed.py
```

- `app/` — API entry point, domain logic, data models, schemas, and supporting services.
- `alembic/` — Database migration configuration and migration revisions.
- `tests/` — Automated tests and shared fixtures.
- `seed.py` — Script to rebuild the database with demo data.
