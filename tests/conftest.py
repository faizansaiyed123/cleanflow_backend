import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point at an isolated temp SQLite DB per test session before any app modules load.
_tmp_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir}/test_cleanflow.db"
os.environ["UPLOAD_ROOT"] = f"{_tmp_dir}/uploads"
os.environ["DISABLE_BACKGROUND_WORKER"] = "true"

from app.config.database import Base, engine, SessionLocal
import app.config.model_registry  # noqa
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Tests share one process (and therefore one in-memory limiter
    instance) with every other test, so without a reset the login rate
    limiter would trip after the 5th test that logs in -- not because
    of a bug, but because the limiter is doing exactly its job. Real
    traffic doesn't have this problem since it isn't 200 login calls in
    9 seconds from the same test-runner IP."""
    from app.observability.rate_limit import login_limiter, public_quote_limiter
    login_limiter.reset()
    public_quote_limiter.reset()
    yield


def auth_header(client, email, password="Demo1234!"):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
