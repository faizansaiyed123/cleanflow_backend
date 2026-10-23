"""
Importing every model module here (even though nothing in this file is
used directly) guarantees SQLAlchemy's Base.metadata knows about every
table before Base.metadata.create_all() runs in main.py. This project
uses create_all() for simplicity (appropriate for a demo/portfolio app);
a production deployment would use Alembic migrations instead -- see
README "Architectural decisions".
"""
from app.users import models as _users_models  # noqa: F401
from app.customers import models as _customers_models  # noqa: F401
from app.employees import models as _employees_models  # noqa: F401
from app.leads import models as _leads_models  # noqa: F401
from app.services import models as _services_models  # noqa: F401
from app.pricing import models as _pricing_models  # noqa: F401
from app.quotes import models as _quotes_models  # noqa: F401
from app.contracts import models as _contracts_models  # noqa: F401
from app.scheduling import models as _scheduling_models  # noqa: F401
from app.jobs import models as _jobs_models  # noqa: F401
from app.invoices import models as _invoices_models  # noqa: F401
from app.payments import models as _payments_models  # noqa: F401
from app.feedback import models as _feedback_models  # noqa: F401
from app.notifications import models as _notifications_models  # noqa: F401
from app.audit import models as _audit_models  # noqa: F401
from app.config import models as _company_settings_models  # noqa: F401
from app.common import reference_numbers as _reference_numbers_model  # noqa: F401
from app.events import models as _events_models  # noqa: F401
from app.webhooks import models as _webhooks_models  # noqa: F401
from app.feature_flags import models as _feature_flags_models  # noqa: F401
from app.idempotency import models as _idempotency_models  # noqa: F401
from app.reports import rollup as _reports_rollup_models  # noqa: F401
