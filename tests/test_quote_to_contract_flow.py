"""
End-to-end test of the flagship automation: quote acceptance ->
contract + recurring schedule + generated jobs, and its idempotency
guarantee (accepting twice never creates a duplicate contract).
"""
import pytest
from datetime import datetime, timedelta

from app.users.models import User
from app.auth.security import hash_password
from app.common.enums import UserRole, PropertyType
from app.pricing.models import PricingRule
from app.services.models import Service


@pytest.fixture()
def staff_and_pricing(db):
    manager = db.query(User).filter(User.email == "flow_manager@test.demo").first()
    if not manager:
        manager = User(email="flow_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                        full_name="Flow Manager", role=UserRole.MANAGER)
        db.add(manager)
    rule = db.query(PricingRule).filter(PricingRule.property_type == PropertyType.RETAIL).first()
    if not rule:
        rule = PricingRule(property_type=PropertyType.RETAIL, base_rate=90, rate_per_sqft=0.04,
                            rate_per_bathroom=15, rate_per_floor_above_one=10, supplies_flat_fee=15,
                            frequency_adjustments={"WEEKLY": -0.1}, is_active=True)
        db.add(rule)
    service = db.query(Service).filter(Service.name == "Flow Test Cleaning").first()
    if not service:
        service = Service(name="Flow Test Cleaning", base_rate=90)
        db.add(service)
    db.commit()
    return manager, service


def manager_headers(client):
    resp = client.post("/api/auth/login", json={"email": "flow_manager@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_quote_acceptance_creates_contract_schedule_and_jobs(client, staff_and_pricing):
    manager, service = staff_and_pricing
    headers = manager_headers(client)

    lead_resp = client.post("/api/public/quote-requests", json={
        "contact_name": "Test Prospect", "email": "prospect@test.demo", "phone": "555-1234",
        "address_line1": "1 Test St", "city": "Austin", "state": "TX", "zip_code": "78701",
        "property_type": "RETAIL", "square_footage": 2000, "bathrooms": 2, "floors": 1,
        "frequency": "WEEKLY",
    })
    assert lead_resp.status_code == 201
    lead_ref = lead_resp.json()["reference_number"]

    leads = client.get("/api/leads", headers=headers).json()["items"]
    lead = next(l for l in leads if l["reference_number"] == lead_ref)

    quote_resp = client.post("/api/quotes", headers=headers, json={
        "lead_id": lead["id"], "primary_service_id": service.id, "property_type": "RETAIL",
        "square_footage": 2000, "bathrooms": 2, "floors": 1, "frequency": "WEEKLY",
    })
    assert quote_resp.status_code == 201, quote_resp.text
    quote = quote_resp.json()
    assert quote["total"] > 0
    assert "line_items" in quote["pricing_breakdown"]

    send_resp = client.post(f"/api/quotes/{quote['id']}/send", headers=headers)
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "SENT"

    # Customer portal login was auto-provisioned when the quote was created.
    customer_login = client.post("/api/auth/login", json={"email": "prospect@test.demo", "password": "Welcome123!"})
    assert customer_login.status_code == 200
    cust_headers = {"Authorization": f"Bearer {customer_login.json()['access_token']}"}

    accept_resp = client.post(f"/api/quotes/{quote['id']}/accept", headers=cust_headers)
    assert accept_resp.status_code == 200, accept_resp.text
    contract = accept_resp.json()
    assert contract["status"] == "ACTIVE"
    assert contract["frequency"] == "WEEKLY"

    # Idempotency: accepting again must return the SAME contract, not a new one.
    accept_again = client.post(f"/api/quotes/{quote['id']}/accept", headers=cust_headers)
    assert accept_again.status_code == 200
    assert accept_again.json()["id"] == contract["id"]

    jobs_resp = client.get("/api/jobs", headers=headers, params={"customer_id": contract["customer_id"]})
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()["items"]
    assert len(jobs) > 0, "Contract acceptance should have generated at least one job"


def test_quote_cannot_be_accepted_twice_from_scratch_without_double_contract(client, staff_and_pricing, db):
    """Even if called concurrently/out of order, there is only ever one
    Contract per Quote (unique FK on Contract.originating_quote_id)."""
    from app.contracts.models import Contract
    manager, service = staff_and_pricing
    headers = manager_headers(client)

    lead_resp = client.post("/api/public/quote-requests", json={
        "contact_name": "Second Prospect", "email": "prospect2@test.demo", "phone": "555-4321",
        "property_type": "RETAIL", "square_footage": 1500, "bathrooms": 1, "floors": 1, "frequency": "MONTHLY",
    })
    lead_id = next(l["id"] for l in client.get("/api/leads", headers=headers).json()["items"]
                   if l["reference_number"] == lead_resp.json()["reference_number"])

    quote = client.post("/api/quotes", headers=headers, json={
        "lead_id": lead_id, "primary_service_id": service.id, "property_type": "RETAIL",
        "square_footage": 1500, "bathrooms": 1, "floors": 1, "frequency": "MONTHLY",
    }).json()
    client.post(f"/api/quotes/{quote['id']}/send", headers=headers)

    cust_login = client.post("/api/auth/login", json={"email": "prospect2@test.demo", "password": "Welcome123!"})
    cust_headers = {"Authorization": f"Bearer {cust_login.json()['access_token']}"}

    r1 = client.post(f"/api/quotes/{quote['id']}/accept", headers=cust_headers)
    r2 = client.post(f"/api/quotes/{quote['id']}/accept", headers=cust_headers)
    assert r1.json()["id"] == r2.json()["id"]

    count = db.query(Contract).filter(Contract.originating_quote_id == quote["id"]).count()
    assert count == 1
