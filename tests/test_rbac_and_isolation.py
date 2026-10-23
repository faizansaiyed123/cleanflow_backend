"""RBAC enforcement and customer data isolation tests."""
import pytest

from app.users.models import User
from app.customers.models import Customer
from app.auth.security import hash_password
from app.common.enums import UserRole


@pytest.fixture()
def two_customers_and_staff(db):
    owner = db.query(User).filter(User.email == "rbac_owner@test.demo").first()
    if not owner:
        owner = User(email="rbac_owner@test.demo", hashed_password=hash_password("Demo1234!"),
                     full_name="RBAC Owner", role=UserRole.OWNER)
        db.add(owner)
    manager = db.query(User).filter(User.email == "rbac_manager@test.demo").first()
    if not manager:
        manager = User(email="rbac_manager@test.demo", hashed_password=hash_password("Demo1234!"),
                       full_name="RBAC Manager", role=UserRole.MANAGER)
        db.add(manager)
    db.flush()

    cust_a = db.query(Customer).filter(Customer.email == "a@test.demo").first()
    cust_b = db.query(Customer).filter(Customer.email == "b@test.demo").first()
    if not cust_a:
        cust_a = Customer(contact_name="Customer A", email="a@test.demo", phone="555-0001")
        db.add(cust_a)
    if not cust_b:
        cust_b = Customer(contact_name="Customer B", email="b@test.demo", phone="555-0002")
        db.add(cust_b)
    db.flush()

    if not db.query(User).filter(User.email == "a@test.demo").first():
        db.add(User(email="a@test.demo", hashed_password=hash_password("Demo1234!"), full_name="Customer A",
                    role=UserRole.CUSTOMER, customer_id=cust_a.id))
    if not db.query(User).filter(User.email == "b@test.demo").first():
        db.add(User(email="b@test.demo", hashed_password=hash_password("Demo1234!"), full_name="Customer B",
                    role=UserRole.CUSTOMER, customer_id=cust_b.id))
    db.commit()
    return {"cust_a": cust_a, "cust_b": cust_b}


def test_unauthenticated_request_rejected(client):
    resp = client.get("/api/customers")
    assert resp.status_code == 401


def test_customer_cannot_view_another_customers_record(client, two_customers_and_staff):
    login = client.post("/api/auth/login", json={"email": "a@test.demo", "password": "Demo1234!"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    own_id = two_customers_and_staff["cust_a"].id
    other_id = two_customers_and_staff["cust_b"].id

    resp_own = client.get(f"/api/customers/{own_id}", headers=headers)
    assert resp_own.status_code == 200

    resp_other = client.get(f"/api/customers/{other_id}", headers=headers)
    assert resp_other.status_code == 403


def test_customer_cannot_list_all_customers(client, two_customers_and_staff):
    login = client.post("/api/auth/login", json={"email": "a@test.demo", "password": "Demo1234!"})
    token = login.json()["access_token"]
    resp = client.get("/api/customers", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_manager_cannot_reach_owner_only_audit_log(client, two_customers_and_staff):
    login = client.post("/api/auth/login", json={"email": "rbac_manager@test.demo", "password": "Demo1234!"})
    token = login.json()["access_token"]
    resp = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_owner_can_reach_audit_log(client, two_customers_and_staff):
    login = client.post("/api/auth/login", json={"email": "rbac_owner@test.demo", "password": "Demo1234!"})
    token = login.json()["access_token"]
    resp = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_wrong_password_rejected(client, two_customers_and_staff):
    resp = client.post("/api/auth/login", json={"email": "a@test.demo", "password": "wrong-password"})
    assert resp.status_code == 401
