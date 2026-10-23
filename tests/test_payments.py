"""Partial payments, overpayment protection, and status derivation."""
import pytest
from datetime import datetime, timedelta

from app.users.models import User
from app.customers.models import Customer
from app.invoices.models import Invoice, InvoiceItem
from app.auth.security import hash_password
from app.common.enums import UserRole, InvoiceStatus
from app.common.reference_numbers import next_reference


@pytest.fixture()
def sent_invoice(db):
    manager = db.query(User).filter(User.email == "pay_manager@test.demo").first()
    if not manager:
        manager = User(email="pay_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                        full_name="Pay Manager", role=UserRole.MANAGER)
        db.add(manager)
    customer = Customer(contact_name="Pay Customer", email="pay_cust@test.demo", phone="555-0002")
    db.add(customer)
    db.flush()
    invoice = Invoice(reference_number=next_reference(db, "invoice"), customer_id=customer.id,
                       status=InvoiceStatus.SENT, due_date=datetime.utcnow() + timedelta(days=10))
    db.add(invoice)
    db.flush()
    db.add(InvoiceItem(invoice_id=invoice.id, description="Test service", amount=200.0))
    db.flush()
    invoice.subtotal = 200.0
    invoice.total = 200.0
    db.commit()
    return invoice


def manager_headers(client):
    resp = client.post("/api/auth/login", json={"email": "pay_manager@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_partial_payment_sets_partially_paid_status(client, sent_invoice):
    headers = manager_headers(client)
    resp = client.post(f"/api/invoices/{sent_invoice.id}/payments", headers=headers, json={
        "amount": 80.0, "method": "CASH",
    })
    assert resp.status_code == 201

    inv = client.get(f"/api/invoices/{sent_invoice.id}", headers=headers).json()
    assert inv["status"] == "PARTIALLY_PAID"
    assert inv["amount_paid"] == 80.0
    assert inv["balance_due"] == 120.0


def test_full_payment_marks_invoice_paid(client, sent_invoice):
    headers = manager_headers(client)
    client.post(f"/api/invoices/{sent_invoice.id}/payments", headers=headers, json={"amount": 200.0, "method": "CHECK"})
    inv = client.get(f"/api/invoices/{sent_invoice.id}", headers=headers).json()
    assert inv["status"] == "PAID"
    assert inv["balance_due"] == 0.0


def test_payment_cannot_exceed_balance_without_explicit_opt_in(client, sent_invoice):
    headers = manager_headers(client)
    resp = client.post(f"/api/invoices/{sent_invoice.id}/payments", headers=headers, json={
        "amount": 500.0, "method": "CASH",
    })
    assert resp.status_code == 409


def test_overpayment_allowed_when_explicitly_flagged(client, sent_invoice):
    headers = manager_headers(client)
    resp = client.post(f"/api/invoices/{sent_invoice.id}/payments", headers=headers, json={
        "amount": 500.0, "method": "CASH", "allow_overpayment": True,
    })
    assert resp.status_code == 201


def test_employee_cannot_access_invoices(client, sent_invoice, db):
    from app.employees.models import Employee
    employee = Employee(full_name="Pay Test Emp", email="pay_emp@test.demo", phone="555-9999")
    db.add(employee)
    db.flush()
    db.add(User(email="pay_emp@test.demo", hashed_password=hash_password("Demo1234!"), full_name="Pay Test Emp",
                role=UserRole.EMPLOYEE, employee_id=employee.id))
    db.commit()

    login = client.post("/api/auth/login", json={"email": "pay_emp@test.demo", "password": "Demo1234!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/invoices", headers=headers)
    assert resp.status_code == 403


def test_cannot_void_invoice_with_payments(client, sent_invoice):
    headers = manager_headers(client)
    client.post(f"/api/invoices/{sent_invoice.id}/payments", headers=headers, json={"amount": 50.0, "method": "CASH"})
    resp = client.post(f"/api/invoices/{sent_invoice.id}/void", headers=headers)
    assert resp.status_code == 409
