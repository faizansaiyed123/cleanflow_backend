"""
Optimistic concurrency control and idempotency-key tests. These
simulate the exact race conditions the patterns exist to prevent,
rather than just checking the code paths execute.
"""
from datetime import datetime, timedelta
import pytest

from app.users.models import User
from app.customers.models import Customer, Property
from app.jobs.models import Job
from app.invoices.models import Invoice, InvoiceItem
from app.auth.security import hash_password
from app.common.enums import UserRole, InvoiceStatus
from app.common.reference_numbers import next_reference


@pytest.fixture()
def manager_and_job(db):
    manager = db.query(User).filter(User.email == "concur_manager@test.demo").first()
    if not manager:
        manager = User(email="concur_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                        full_name="Concurrency Manager", role=UserRole.MANAGER)
        db.add(manager)
    customer = Customer(contact_name="Concur Customer", email=f"concur_{datetime.utcnow().timestamp()}@test.demo", phone="555-1000")
    db.add(customer)
    db.flush()
    prop = Property(customer_id=customer.id, label="Site", address_line1="1 St", city="Austin", state="TX",
                     zip_code="78701", square_footage=1000)
    db.add(prop)
    db.flush()
    job = Job(reference_number=next_reference(db, "job"), customer_id=customer.id, property_id=prop.id,
              scheduled_start=datetime.utcnow() + timedelta(days=1),
              scheduled_end=datetime.utcnow() + timedelta(days=1, hours=1))
    db.add(job)
    db.commit()
    return job


def manager_headers(client):
    resp = client.post("/api/auth/login", json={"email": "concur_manager@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_job_starts_at_version_one(client, manager_and_job):
    headers = manager_headers(client)
    resp = client.get(f"/api/jobs/{manager_and_job.id}", headers=headers)
    assert resp.json()["version"] == 1


def test_reschedule_with_correct_version_succeeds_and_bumps_version(client, manager_and_job):
    headers = manager_headers(client)
    job_id = manager_and_job.id
    new_start = (datetime.utcnow() + timedelta(days=2)).isoformat()
    new_end = (datetime.utcnow() + timedelta(days=2, hours=1)).isoformat()

    resp = client.post(f"/api/jobs/{job_id}/reschedule", headers=headers,
                        json={"scheduled_start": new_start, "scheduled_end": new_end, "expected_version": 1})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2


def test_two_concurrent_edits_second_one_is_rejected(client, manager_and_job):
    """
    The core scenario: two managers (or two browser tabs) both load the
    job at version 1, then both try to act on it. The first write wins
    and moves the version to 2; the second write, still carrying
    expected_version=1, must be rejected with 409 rather than silently
    overwriting the first manager's change.
    """
    headers = manager_headers(client)
    job_id = manager_and_job.id

    # Manager A reschedules first (succeeds, job is now version 2).
    new_start_a = (datetime.utcnow() + timedelta(days=3)).isoformat()
    new_end_a = (datetime.utcnow() + timedelta(days=3, hours=1)).isoformat()
    resp_a = client.post(f"/api/jobs/{job_id}/reschedule", headers=headers,
                          json={"scheduled_start": new_start_a, "scheduled_end": new_end_a, "expected_version": 1})
    assert resp_a.status_code == 200

    # Manager B, who loaded the job before A's change, still thinks it's
    # version 1 and tries to cancel it.
    resp_b = client.post(f"/api/jobs/{job_id}/cancel", headers=headers,
                          json={"reason": "Customer requested cancellation", "expected_version": 1})
    assert resp_b.status_code == 409
    assert "modified by someone else" in resp_b.json()["detail"]

    # The job must reflect A's change, not have been silently cancelled by B.
    final = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    assert final["status"] != "CANCELLED"
    assert final["version"] == 2


def test_omitting_expected_version_skips_the_check(client, manager_and_job):
    """Version checking is opt-in per request (not a breaking change for
    callers that don't send it), so omitting it entirely must still work."""
    headers = manager_headers(client)
    resp = client.post(f"/api/jobs/{manager_and_job.id}/cancel", headers=headers, json={"reason": "No version supplied"})
    assert resp.status_code == 200


# --- Idempotency-Key tests -------------------------------------------------

@pytest.fixture()
def sent_invoice_for_idem(db):
    manager = db.query(User).filter(User.email == "idem_manager@test.demo").first()
    if not manager:
        manager = User(email="idem_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                        full_name="Idem Manager", role=UserRole.MANAGER)
        db.add(manager)
    customer = Customer(contact_name="Idem Customer", email=f"idem_{datetime.utcnow().timestamp()}@test.demo", phone="555-2000")
    db.add(customer)
    db.flush()
    invoice = Invoice(reference_number=next_reference(db, "invoice"), customer_id=customer.id,
                       status=InvoiceStatus.SENT, due_date=datetime.utcnow() + timedelta(days=10), total=200.0)
    db.add(invoice)
    db.flush()
    db.add(InvoiceItem(invoice_id=invoice.id, description="Test", amount=200.0))
    db.commit()
    return invoice


def idem_manager_headers(client):
    resp = client.post("/api/auth/login", json={"email": "idem_manager@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_duplicate_idempotency_key_does_not_double_charge(client, sent_invoice_for_idem, db):
    headers = idem_manager_headers(client)
    headers["Idempotency-Key"] = "retry-test-key-001"
    invoice_id = sent_invoice_for_idem.id
    body = {"amount": 100.0, "method": "CASH"}

    resp1 = client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json=body)
    assert resp1.status_code == 201

    # Simulate the client retrying after a dropped response, same key, same body.
    resp2 = client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json=body)
    assert resp2.status_code == 201
    assert resp2.json()["id"] == resp1.json()["id"]  # same payment returned, not a new one

    db.refresh(sent_invoice_for_idem)
    assert sent_invoice_for_idem.amount_paid == 100.0  # NOT 200.0 -- only charged once


def test_reusing_idempotency_key_with_different_body_is_rejected(client, sent_invoice_for_idem):
    headers = idem_manager_headers(client)
    headers["Idempotency-Key"] = "retry-test-key-002"
    invoice_id = sent_invoice_for_idem.id

    resp1 = client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json={"amount": 50.0, "method": "CASH"})
    assert resp1.status_code == 201

    resp2 = client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json={"amount": 999.0, "method": "CHECK"})
    assert resp2.status_code == 409


def test_different_idempotency_keys_both_charge(client, sent_invoice_for_idem, db):
    headers = idem_manager_headers(client)
    invoice_id = sent_invoice_for_idem.id

    h1 = {**headers, "Idempotency-Key": "key-a"}
    h2 = {**headers, "Idempotency-Key": "key-b"}
    client.post(f"/api/invoices/{invoice_id}/payments", headers=h1, json={"amount": 60.0, "method": "CASH"})
    client.post(f"/api/invoices/{invoice_id}/payments", headers=h2, json={"amount": 40.0, "method": "CASH"})

    db.refresh(sent_invoice_for_idem)
    assert sent_invoice_for_idem.amount_paid == 100.0
