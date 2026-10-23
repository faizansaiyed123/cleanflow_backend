"""Tests for pagination, PDF export, bulk operations, CSV export, and
the customer service timeline added in the second implementation pass."""
import pytest
from datetime import datetime, timedelta

from app.users.models import User
from app.customers.models import Customer, Property
from app.employees.models import Employee
from app.contracts.models import Contract
from app.invoices.models import Invoice, InvoiceItem
from app.jobs.models import Job, JobAssignment
from app.auth.security import hash_password
from app.common.enums import UserRole, InvoiceStatus, CleaningFrequency
from app.common.reference_numbers import next_reference


@pytest.fixture()
def owner_headers(client):
    owner = None
    resp = client.post("/api/auth/login", json={"email": "owner@cleanflow.demo", "password": "Demo1234!"})
    if resp.status_code == 200:
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return None


@pytest.fixture()
def bootstrap_staff(db):
    owner = db.query(User).filter(User.email == "feat_owner@test.demo").first()
    if not owner:
        owner = User(email="feat_owner@test.demo", hashed_password=hash_password("Demo1234!"),
                     full_name="Feature Owner", role=UserRole.OWNER)
        db.add(owner)
        db.commit()
    return owner


def owner_login(client):
    resp = client.post("/api/auth/login", json={"email": "feat_owner@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_leads_list_is_paginated(client, bootstrap_staff, db):
    for i in range(3):
        from app.leads.models import Lead
        from app.common.enums import LeadStatus, LeadSource, PropertyType
        db.add(Lead(reference_number=next_reference(db, "lead"), contact_name=f"Page Test {i}",
                     email=f"pt{i}@test.demo", phone="555-0000", property_type=PropertyType.OFFICE,
                     source=LeadSource.WEBSITE, status=LeadStatus.NEW))
    db.commit()
    headers = owner_login(client)
    resp = client.get("/api/leads", headers=headers, params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "page", "page_size"}
    assert len(data["items"]) == 2
    assert data["total"] >= 3


def test_customers_csv_export(client, bootstrap_staff, db):
    customer = Customer(contact_name="CSV Test", email="csvtest@test.demo", phone="555-1111")
    db.add(customer)
    db.commit()
    headers = owner_login(client)
    resp = client.get("/api/customers/export/csv", headers=headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "CSV Test" in resp.text


def test_quote_pdf_download(client, bootstrap_staff, db):
    from app.quotes.models import Quote
    from app.common.enums import QuoteStatus, PropertyType

    customer = Customer(contact_name="PDF Customer", email="pdfcust@test.demo", phone="555-2222")
    db.add(customer)
    db.flush()
    quote = Quote(reference_number=next_reference(db, "quote"), customer_id=customer.id,
                  property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
                  frequency=CleaningFrequency.WEEKLY, pricing_breakdown={"line_items": [{"label": "Base service", "amount": 100, "kind": "charge"}], "subtotal": 100, "total": 100},
                  subtotal=100, total=100, status=QuoteStatus.DRAFT, valid_until=datetime.utcnow() + timedelta(days=14))
    db.add(quote)
    db.commit()
    headers = owner_login(client)
    resp = client.get(f"/api/quotes/{quote.id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_invoice_pdf_download(client, bootstrap_staff, db):
    customer = Customer(contact_name="Invoice PDF Customer", email="invpdf@test.demo", phone="555-3333")
    db.add(customer)
    db.flush()
    invoice = Invoice(reference_number=next_reference(db, "invoice"), customer_id=customer.id,
                       status=InvoiceStatus.SENT, due_date=datetime.utcnow() + timedelta(days=10),
                       subtotal=200, total=200)
    db.add(invoice)
    db.flush()
    db.add(InvoiceItem(invoice_id=invoice.id, description="Test", amount=200))
    db.commit()
    headers = owner_login(client)
    resp = client.get(f"/api/invoices/{invoice.id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_bulk_assign_jobs(client, bootstrap_staff, db):
    employee = Employee(full_name="Bulk Test Employee", email="bulkemp@test.demo", phone="555-4444")
    db.add(employee)
    customer = Customer(contact_name="Bulk Customer", email="bulkcust@test.demo", phone="555-5555")
    db.add(customer)
    db.flush()
    prop = Property(customer_id=customer.id, label="Site", address_line1="1 St", city="Austin", state="TX",
                     zip_code="78701", square_footage=1000)
    db.add(prop)
    db.flush()
    jobs = []
    for i in range(2):
        job = Job(reference_number=next_reference(db, "job"), customer_id=customer.id, property_id=prop.id,
                  scheduled_start=datetime.utcnow() + timedelta(days=i + 1),
                  scheduled_end=datetime.utcnow() + timedelta(days=i + 1, hours=1))
        db.add(job)
        jobs.append(job)
    db.commit()

    headers = owner_login(client)
    resp = client.post("/api/jobs/bulk-assign", headers=headers,
                        json={"job_ids": [j.id for j in jobs], "employee_ids": [employee.id]})
    assert resp.status_code == 200
    result = resp.json()
    assert len(result["assigned"]) == 2
    assert len(result["failed"]) == 0


def test_bulk_send_invoices(client, bootstrap_staff, db):
    customer = Customer(contact_name="Bulk Invoice Customer", email="bulkinv@test.demo", phone="555-6666")
    db.add(customer)
    db.flush()
    invoices = []
    for i in range(2):
        inv = Invoice(reference_number=next_reference(db, "invoice"), customer_id=customer.id,
                       status=InvoiceStatus.DRAFT, due_date=datetime.utcnow() + timedelta(days=10),
                       subtotal=100, total=100)
        db.add(inv)
        invoices.append(inv)
    db.commit()

    headers = owner_login(client)
    resp = client.post("/api/invoices/bulk-send", headers=headers, json={"invoice_ids": [i.id for i in invoices]})
    assert resp.status_code == 200
    result = resp.json()
    assert len(result["sent"]) == 2
    for inv in invoices:
        db.refresh(inv)
        assert inv.status == InvoiceStatus.SENT


def test_customer_timeline_orders_events_chronologically(client, bootstrap_staff, db):
    from app.leads.models import Lead
    from app.quotes.models import Quote
    from app.common.enums import LeadStatus, LeadSource, PropertyType, QuoteStatus

    customer = Customer(contact_name="Timeline Customer", email="timeline@test.demo", phone="555-7777")
    db.add(customer)
    db.flush()
    lead = Lead(reference_number=next_reference(db, "lead"), contact_name="Timeline Customer",
                email="timeline@test.demo", phone="555-7777", property_type=PropertyType.OFFICE,
                source=LeadSource.WEBSITE, status=LeadStatus.WON, converted_customer_id=customer.id,
                created_at=datetime.utcnow() - timedelta(days=10))
    db.add(lead)
    quote = Quote(reference_number=next_reference(db, "quote"), customer_id=customer.id, lead_id=None,
                  property_type=PropertyType.OFFICE, square_footage=1000, bathrooms=1, floors=1,
                  frequency=CleaningFrequency.WEEKLY, pricing_breakdown={"line_items": [], "subtotal": 100, "total": 100},
                  subtotal=100, total=100, status=QuoteStatus.ACCEPTED, valid_until=datetime.utcnow() + timedelta(days=14),
                  created_at=datetime.utcnow() - timedelta(days=8))
    db.add(quote)
    db.commit()

    headers = owner_login(client)
    resp = client.get(f"/api/customers/{customer.id}/timeline", headers=headers)
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 2
    timestamps = [e["at"] for e in events]
    assert timestamps == sorted(timestamps)


def test_customer_cannot_view_another_customers_timeline(client, db):
    customer_a = Customer(contact_name="Timeline A", email="timelinea@test.demo", phone="555-8888")
    customer_b = Customer(contact_name="Timeline B", email="timelineb@test.demo", phone="555-9999")
    db.add_all([customer_a, customer_b])
    db.flush()
    db.add(User(email="timelinea@test.demo", hashed_password=hash_password("Demo1234!"), full_name="Timeline A",
                role=UserRole.CUSTOMER, customer_id=customer_a.id))
    db.commit()

    login = client.post("/api/auth/login", json={"email": "timelinea@test.demo", "password": "Demo1234!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get(f"/api/customers/{customer_b.id}/timeline", headers=headers)
    assert resp.status_code == 403
