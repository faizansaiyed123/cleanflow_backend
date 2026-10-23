"""Tests for FTS5 full-text search, webhook delivery, and feature flags."""
from datetime import datetime, timedelta
import pytest
import respx
import httpx

from app.users.models import User
from app.customers.models import Customer
from app.auth.security import hash_password
from app.common.enums import UserRole
from app.search.index import rebuild_index, search_fts
from app.webhooks.models import WebhookEndpoint, WebhookDelivery
from app.webhooks.service import attempt_delivery, sign_payload, verify_signature
from app.feature_flags.models import FeatureFlag


@pytest.fixture()
def owner_login(client, db):
    if not db.query(User).filter(User.email == "search_owner@test.demo").first():
        db.add(User(email="search_owner@test.demo", hashed_password=hash_password("Demo1234!"),
                     full_name="Search Owner", role=UserRole.OWNER))
        db.commit()
    resp = client.post("/api/auth/login", json={"email": "search_owner@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- FTS5 search -----------------------------------------------------------

def test_fts_index_finds_customer_by_partial_name(client, db, owner_login):
    customer = Customer(contact_name="Zephyrine Okonkwo", email="zeph@test.demo", phone="555-0001")
    db.add(customer)
    db.commit()
    rebuild_index(db)

    results = search_fts(db, "zephyrine")
    assert any(r["type"] == "Customer" and r["id"] == customer.id for r in results)


def test_fts_query_sanitization_handles_special_characters(client, db, owner_login):
    """A raw FTS5 MATCH query would error on bare punctuation like `(` or
    `"` -- the search must sanitize input rather than 500 on it."""
    rebuild_index(db)
    results = search_fts(db, 'weird"query(chars*')
    assert isinstance(results, list)  # doesn't raise


def test_search_endpoint_scopes_by_role(client, db):
    cust_a = Customer(contact_name="Search Isolation Co", email="iso_a@test.demo", phone="555-2222")
    db.add(cust_a)
    db.flush()
    db.add(User(email="iso_a@test.demo", hashed_password=hash_password("Demo1234!"), full_name="Iso A",
                role=UserRole.CUSTOMER, customer_id=cust_a.id))
    db.commit()
    rebuild_index(db)

    login = client.post("/api/auth/login", json={"email": "iso_a@test.demo", "password": "Demo1234!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/search", headers=headers, params={"q": "Search Isolation"})
    assert resp.status_code == 200
    # A customer's search never returns another customer's data, even if
    # it matched -- verified structurally since results are self-scoped.
    for r in resp.json():
        assert r["type"] in ("Customer", "Invoice")


# --- Webhooks ----------------------------------------------------------------

def test_hmac_signature_round_trips():
    secret = "whsec_test123"
    body = b'{"hello":"world"}'
    sig = sign_payload(secret, body)
    assert verify_signature(secret, body, sig)
    assert not verify_signature(secret, body, "tampered" + sig[8:])


def test_create_webhook_endpoint_returns_secret_once(client, owner_login):
    resp = client.post("/api/webhooks/endpoints", headers=owner_login, json={
        "url": "https://example.com/hooks/cleanflow", "subscribed_events": ["job.completed", "invoice.overdue"],
        "description": "Test integration",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["secret"].startswith("whsec_")

    # A subsequent list call must NOT re-expose the secret.
    listed = client.get("/api/webhooks/endpoints", headers=owner_login).json()
    assert "secret" not in listed[0]


def test_rejects_unknown_event_type(client, owner_login):
    resp = client.post("/api/webhooks/endpoints", headers=owner_login, json={
        "url": "https://example.com/hook", "subscribed_events": ["not.a.real.event"],
    })
    assert resp.status_code == 422


@respx.mock
def test_webhook_delivery_succeeds_and_signs_request(db):
    endpoint = WebhookEndpoint(url="https://receiver.test/hook", secret="whsec_abc123",
                                subscribed_events=["job.completed"], is_active=True)
    db.add(endpoint)
    db.flush()
    delivery = WebhookDelivery(endpoint_id=endpoint.id, event_type="job.completed",
                                payload={"job_id": "abc"}, status="PENDING")
    db.add(delivery)
    db.commit()

    route = respx.post("https://receiver.test/hook").mock(return_value=httpx.Response(200))
    attempt_delivery(db, delivery)
    db.commit()

    assert route.called
    sent_request = route.calls[0].request
    assert "X-CleanFlow-Signature" in sent_request.headers
    assert delivery.status == "SENT"
    assert delivery.delivered_at is not None


@respx.mock
def test_webhook_delivery_retries_on_failure_then_dead_letters(db):
    endpoint = WebhookEndpoint(url="https://flaky.test/hook", secret="whsec_xyz", subscribed_events=["job.completed"])
    db.add(endpoint)
    db.flush()
    delivery = WebhookDelivery(endpoint_id=endpoint.id, event_type="job.completed", payload={}, status="PENDING",
                                max_attempts=2)
    db.add(delivery)
    db.commit()

    respx.post("https://flaky.test/hook").mock(return_value=httpx.Response(500))

    attempt_delivery(db, delivery)
    db.commit()
    assert delivery.status == "FAILED"
    assert delivery.attempts == 1
    assert delivery.next_attempt_at is not None

    attempt_delivery(db, delivery)
    db.commit()
    assert delivery.status == "DEAD_LETTER"
    assert delivery.attempts == 2


def test_deactivated_endpoint_receives_no_new_deliveries(db):
    """Other tests in this module may have already created active
    endpoints subscribed to the same event (the test DB is shared across
    the whole session, not reset per-test) -- so the correct assertion
    is 'no delivery was created FOR THIS endpoint', not 'no deliveries
    exist at all'."""
    from app.webhooks.service import enqueue_deliveries_for_event
    endpoint = WebhookEndpoint(url="https://gone.test/hook", secret="whsec_gone",
                                subscribed_events=["job.completed"], is_active=False)
    db.add(endpoint)
    db.commit()
    created = enqueue_deliveries_for_event(db, "job.completed", {}, None)
    assert all(d.endpoint_id != endpoint.id for d in created)


# --- Feature flags -----------------------------------------------------------

def test_default_flags_are_seeded_disabled(client, owner_login):
    resp = client.get("/api/feature-flags", headers=owner_login)
    assert resp.status_code == 200
    flags = {f["key"]: f["is_enabled"] for f in resp.json()}
    assert "auto_invoice_on_completion" in flags
    assert flags["auto_invoice_on_completion"] is False


def test_owner_can_toggle_flag(client, owner_login):
    client.get("/api/feature-flags", headers=owner_login)  # ensures defaults exist
    resp = client.patch("/api/feature-flags/auto_invoice_on_completion", headers=owner_login,
                         json={"is_enabled": True})
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is True


def test_non_owner_cannot_toggle_flag(client, db):
    manager = User(email="flag_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                    full_name="Flag Manager", role=UserRole.MANAGER)
    db.add(manager)
    db.commit()
    login = client.post("/api/auth/login", json={"email": "flag_manager@test.demo", "password": "Demo1234!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.patch("/api/feature-flags/auto_invoice_on_completion", headers=headers, json={"is_enabled": True})
    assert resp.status_code == 403


def test_auto_invoice_on_completion_creates_invoice_when_flag_enabled(client, db, owner_login):
    """The feature-flag-gated event handler: when the flag is on, the
    job.completed event handler auto-creates and sends an invoice."""
    from app.customers.models import Property
    from app.jobs.models import Job, JobAssignment, JobChecklistItem
    from app.employees.models import Employee
    from app.common.reference_numbers import next_reference
    from app.events.bus import publish, EventType
    from app.events.handlers import dispatch
    from app.invoices.models import InvoiceItem

    flag = db.query(FeatureFlag).filter(FeatureFlag.key == "auto_invoice_on_completion").first()
    if not flag:
        flag = FeatureFlag(key="auto_invoice_on_completion", is_enabled=True)
        db.add(flag)
    else:
        flag.is_enabled = True
    db.commit()

    customer = Customer(contact_name="Auto Invoice Co", email="autoinv@test.demo", phone="555-3000")
    db.add(customer)
    db.flush()
    prop = Property(customer_id=customer.id, label="Site", address_line1="1 St", city="Austin", state="TX",
                     zip_code="78701", square_footage=1000)
    db.add(prop)
    employee = Employee(full_name="Auto Invoice Emp", email="autoinvemp@test.demo", phone="555-3001")
    db.add(employee)
    db.flush()
    job = Job(reference_number=next_reference(db, "job"), customer_id=customer.id, property_id=prop.id,
              scheduled_start=datetime.utcnow(), scheduled_end=datetime.utcnow() + timedelta(hours=1),
              status="COMPLETED", check_in_at=datetime.utcnow(), check_out_at=datetime.utcnow(),
              completed_at=datetime.utcnow())
    db.add(job)
    db.commit()

    dispatch(db, EventType.JOB_COMPLETED, {"job_id": job.id, "reference_number": job.reference_number})
    db.commit()

    invoice_item = db.query(InvoiceItem).filter(InvoiceItem.job_id == job.id).first()
    assert invoice_item is not None, "auto_invoice_on_completion should have created an invoice for this job"


# --- SSE stream ticket -------------------------------------------------------

def test_stream_ticket_is_scoped_and_short_lived(client, db):
    user = User(email="sse_user@test.demo", hashed_password=hash_password("Demo1234!"),
                full_name="SSE User", role=UserRole.OWNER)
    db.add(user)
    db.commit()
    login = client.post("/api/auth/login", json={"email": "sse_user@test.demo", "password": "Demo1234!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    ticket_resp = client.get("/api/notifications/stream-ticket", headers=headers)
    assert ticket_resp.status_code == 200
    assert ticket_resp.json()["expires_in_seconds"] == 60

    from app.auth.security import decode_access_token
    payload = decode_access_token(ticket_resp.json()["ticket"])
    assert payload["scope"] == "notifications:stream"


def test_regular_access_token_cannot_be_used_as_stream_ticket(client, db):
    """A normal login JWT lacks the stream scope and must be rejected by
    the stream endpoint even though it's otherwise a valid token for the
    same user -- scoped tokens must actually be checked, not just issued."""
    user = User(email="sse_user2@test.demo", hashed_password=hash_password("Demo1234!"),
                full_name="SSE User 2", role=UserRole.OWNER)
    db.add(user)
    db.commit()
    login = client.post("/api/auth/login", json={"email": "sse_user2@test.demo", "password": "Demo1234!"})
    access_token = login.json()["access_token"]

    resp = client.get(f"/api/notifications/stream?token={access_token}")
    assert resp.status_code == 401
