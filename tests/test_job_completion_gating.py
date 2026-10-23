"""
Job completion is gated on: checked in -> checked out -> all required
checklist items complete -> required proof photos present. Nothing can
skip this server-side, regardless of what the client sends.
"""
import pytest
from datetime import datetime, timedelta

from app.users.models import User
from app.employees.models import Employee
from app.customers.models import Customer, Property
from app.jobs.models import Job, JobAssignment, JobChecklistItem
from app.auth.security import hash_password
from app.common.enums import UserRole, JobStatus
from app.common.reference_numbers import next_reference


@pytest.fixture()
def job_with_employee(db):
    employee = db.query(Employee).filter(Employee.email == "gate_emp@test.demo").first()
    if not employee:
        employee = Employee(full_name="Gate Test Employee", email="gate_emp@test.demo", phone="555-0000")
        db.add(employee)
        db.flush()
        db.add(User(email="gate_emp@test.demo", hashed_password=hash_password("Demo1234!"),
                     full_name="Gate Test Employee", role=UserRole.EMPLOYEE, employee_id=employee.id))

    customer = Customer(contact_name="Gate Customer", email=f"gate_cust_{datetime.utcnow().timestamp()}@test.demo",
                         phone="555-0001")
    db.add(customer)
    db.flush()
    prop = Property(customer_id=customer.id, label="Site", address_line1="1 St", city="Austin", state="TX",
                     zip_code="78701", square_footage=1000)
    db.add(prop)
    db.flush()

    job = Job(reference_number=next_reference(db, "job"), customer_id=customer.id, property_id=prop.id,
               scheduled_start=datetime.utcnow(), scheduled_end=datetime.utcnow() + timedelta(hours=1))
    db.add(job)
    db.flush()
    db.add(JobAssignment(job_id=job.id, employee_id=employee.id))
    db.add(JobChecklistItem(job_id=job.id, label="Required task", is_required=True))
    db.add(JobChecklistItem(job_id=job.id, label="Optional task", is_required=False))
    db.commit()
    return job


def emp_headers(client):
    resp = client.post("/api/auth/login", json={"email": "gate_emp@test.demo", "password": "Demo1234!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_cannot_check_out_before_check_in(client, job_with_employee):
    headers = emp_headers(client)
    resp = client.post(f"/api/jobs/{job_with_employee.id}/check-out", headers=headers)
    assert resp.status_code == 409


def test_cannot_complete_without_checkin_checkout(client, job_with_employee):
    headers = emp_headers(client)
    resp = client.post(f"/api/jobs/{job_with_employee.id}/complete", headers=headers)
    assert resp.status_code == 409


def test_cannot_complete_with_incomplete_required_checklist_item(client, job_with_employee, db):
    headers = emp_headers(client)
    job_id = job_with_employee.id
    client.post(f"/api/jobs/{job_id}/check-in", headers=headers, json={})
    client.post(f"/api/jobs/{job_id}/check-out", headers=headers)

    resp = client.post(f"/api/jobs/{job_id}/complete", headers=headers)
    assert resp.status_code == 409
    assert "checklist" in resp.json()["detail"].lower()


def test_cannot_complete_without_required_photos(client, job_with_employee, db):
    headers = emp_headers(client)
    job_id = job_with_employee.id
    client.post(f"/api/jobs/{job_id}/check-in", headers=headers, json={})
    client.post(f"/api/jobs/{job_id}/check-out", headers=headers)

    # Complete the required checklist item, but upload NO photos.
    job = db.query(Job).filter(Job.id == job_id).first()
    required_item = next(i for i in job.checklist_items if i.is_required)
    client.patch(f"/api/jobs/{job_id}/checklist/{required_item.id}", headers=headers, json={"is_completed": True})

    resp = client.post(f"/api/jobs/{job_id}/complete", headers=headers)
    assert resp.status_code == 409
    assert "photo" in resp.json()["detail"].lower()


def test_full_valid_workflow_completes_successfully(client, job_with_employee, db):
    headers = emp_headers(client)
    job_id = job_with_employee.id

    assert client.post(f"/api/jobs/{job_id}/check-in", headers=headers, json={}).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/check-out", headers=headers).status_code == 200

    job = db.query(Job).filter(Job.id == job_id).first()
    required_item = next(i for i in job.checklist_items if i.is_required)
    client.patch(f"/api/jobs/{job_id}/checklist/{required_item.id}", headers=headers, json={"is_completed": True})

    for photo_type in ["BEFORE", "AFTER"]:
        resp = client.post(
            f"/api/jobs/{job_id}/photos", headers=headers,
            data={"photo_type": photo_type},
            files={"file": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
        )
        assert resp.status_code == 200, resp.text

    complete_resp = client.post(f"/api/jobs/{job_id}/complete", headers=headers)
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "COMPLETED"


def test_completed_job_cannot_silently_revert(client, job_with_employee, db):
    """A completed job's checklist can no longer be modified."""
    job = db.query(Job).filter(Job.id == job_with_employee.id).first()
    job.status = JobStatus.COMPLETED
    db.commit()

    headers = emp_headers(client)
    item = job.checklist_items[0]
    resp = client.patch(f"/api/jobs/{job.id}/checklist/{item.id}", headers=headers, json={"is_completed": False})
    assert resp.status_code == 409
