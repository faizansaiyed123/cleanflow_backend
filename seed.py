"""
Seed script: wipes and rebuilds the demo database with realistic data,
including the four demo accounts documented in the README.

Run with: python seed.py
"""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app.config.database import Base, engine, SessionLocal
import app.config.model_registry  # noqa

from app.common.enums import (
    UserRole, LeadSource, LeadStatus, PropertyType, CleaningFrequency, QuoteStatus,
    ContractStatus, JobStatus, InvoiceStatus, PaymentMethod, PhotoType,
)
from app.common.reference_numbers import next_reference
from app.auth.security import hash_password
from app.users.models import User
from app.customers.models import Customer, Property
from app.employees.models import Employee
from app.leads.models import Lead
from app.services.models import Service, ChecklistTemplate, ChecklistTemplateItem
from app.pricing.models import PricingRule
from app.quotes.models import Quote, QuoteItem
from app.contracts.models import Contract, ContractService
from app.scheduling.models import RecurringSchedule
from app.scheduling.generator import generate_jobs_for_schedule
from app.jobs.models import Job, JobAssignment, JobChecklistItem, JobPhoto, JobNote
from app.invoices.models import Invoice, InvoiceItem
from app.payments.models import Payment
from app.feedback.models import Feedback
from app.config.models import CompanySetting
from app.pricing.engine import calculate_quote_price, QuoteCalculationInput

now = datetime.utcnow()


def wipe_and_create():
    print("Dropping and recreating all tables...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed():
    db = SessionLocal()
    try:
        # --- Company settings -------------------------------------------------
        db.add(CompanySetting(
            company_name="CleanFlow Commercial Cleaning Co.",
            phone="(555) 010-2020", email="hello@cleanflowdemo.com",
            address="500 Industrial Pkwy, Suite 200, Austin, TX 78701",
            business_hours={"MON": "7:00 AM - 6:00 PM", "TUE": "7:00 AM - 6:00 PM", "WED": "7:00 AM - 6:00 PM",
                             "THU": "7:00 AM - 6:00 PM", "FRI": "7:00 AM - 6:00 PM", "SAT": "Closed", "SUN": "Closed"},
            currency="USD", default_tax_rate_percent=0.0, invoice_due_days=15, quote_validity_days=14,
        ))

        # --- Pricing rules (one per property type) ------------------------------
        pricing_defaults = {
            PropertyType.OFFICE: dict(base_rate=100, rate_per_sqft=0.05, rate_per_bathroom=20, rate_per_floor_above_one=15,
                                       supplies_flat_fee=20, frequency_adjustments={"DAILY": -0.20, "WEEKLY": -0.12,
                                       "BIWEEKLY": -0.06, "MONTHLY": 0.0, "ONE_TIME": 0.10, "CUSTOM": -0.08}),
            PropertyType.RETAIL: dict(base_rate=90, rate_per_sqft=0.045, rate_per_bathroom=18, rate_per_floor_above_one=12,
                                       supplies_flat_fee=18, frequency_adjustments={"DAILY": -0.18, "WEEKLY": -0.10,
                                       "BIWEEKLY": -0.05, "MONTHLY": 0.0, "ONE_TIME": 0.10, "CUSTOM": -0.07}),
            PropertyType.MEDICAL: dict(base_rate=140, rate_per_sqft=0.07, rate_per_bathroom=30, rate_per_floor_above_one=20,
                                        supplies_flat_fee=35, frequency_adjustments={"DAILY": -0.15, "WEEKLY": -0.08,
                                        "BIWEEKLY": -0.04, "MONTHLY": 0.0, "ONE_TIME": 0.15, "CUSTOM": -0.06},
                                        special_condition_surcharge_percent=0.12),
            PropertyType.WAREHOUSE: dict(base_rate=120, rate_per_sqft=0.03, rate_per_bathroom=15, rate_per_floor_above_one=10,
                                          supplies_flat_fee=15, frequency_adjustments={"DAILY": -0.15, "WEEKLY": -0.08,
                                          "BIWEEKLY": -0.04, "MONTHLY": 0.0, "ONE_TIME": 0.10, "CUSTOM": -0.06}),
            PropertyType.RESTAURANT: dict(base_rate=110, rate_per_sqft=0.06, rate_per_bathroom=22, rate_per_floor_above_one=15,
                                           supplies_flat_fee=25, frequency_adjustments={"DAILY": -0.22, "WEEKLY": -0.12,
                                           "BIWEEKLY": -0.06, "MONTHLY": 0.0, "ONE_TIME": 0.12, "CUSTOM": -0.08},
                                           special_condition_surcharge_percent=0.10),
            PropertyType.RESIDENTIAL: dict(base_rate=75, rate_per_sqft=0.04, rate_per_bathroom=15, rate_per_floor_above_one=10,
                                            supplies_flat_fee=15, frequency_adjustments={"DAILY": -0.10, "WEEKLY": -0.08,
                                            "BIWEEKLY": -0.04, "MONTHLY": 0.0, "ONE_TIME": 0.05, "CUSTOM": -0.05}),
            PropertyType.OTHER: dict(base_rate=95, rate_per_sqft=0.05, rate_per_bathroom=18, rate_per_floor_above_one=12,
                                      supplies_flat_fee=18, frequency_adjustments={"DAILY": -0.15, "WEEKLY": -0.10,
                                      "BIWEEKLY": -0.05, "MONTHLY": 0.0, "ONE_TIME": 0.10, "CUSTOM": -0.06}),
        }
        for ptype, cfg in pricing_defaults.items():
            db.add(PricingRule(property_type=ptype, is_active=True, **cfg))
        db.flush()

        # --- Checklist templates -------------------------------------------------
        office_template = ChecklistTemplate(name="Standard Office Cleaning")
        db.add(office_template)
        db.flush()
        for i, (label, required) in enumerate([
            ("Empty all trash and recycling bins", True), ("Vacuum all carpeted areas", True),
            ("Mop hard-surface floors", True), ("Clean and disinfect restrooms", True),
            ("Wipe down desks and common surfaces", True), ("Clean interior glass and doors", False),
            ("Restock restroom and kitchen supplies", True), ("Clean kitchen/break room", True),
        ]):
            db.add(ChecklistTemplateItem(template_id=office_template.id, label=label, is_required=required, sort_order=i))

        medical_template = ChecklistTemplate(name="Medical-Grade Cleaning")
        db.add(medical_template)
        db.flush()
        for i, (label, required) in enumerate([
            ("Disinfect all high-touch surfaces (medical-grade)", True), ("Empty biohazard/sharps-adjacent bins per protocol", True),
            ("Mop and disinfect floors", True), ("Clean and sanitize restrooms", True),
            ("Wipe down exam/waiting room surfaces", True), ("Restock PPE and supply stations", True),
        ]):
            db.add(ChecklistTemplateItem(template_id=medical_template.id, label=label, is_required=required, sort_order=i))
        db.flush()

        # --- Services --------------------------------------------------------
        svc_standard = Service(name="Standard Commercial Cleaning", description="Recurring office/commercial cleaning",
                                base_rate=100, checklist_template_id=office_template.id)
        svc_medical = Service(name="Medical-Grade Cleaning", description="Enhanced disinfection for medical/dental offices",
                               base_rate=140, checklist_template_id=medical_template.id)
        svc_deep = Service(name="Deep Clean", description="One-time intensive deep clean", base_rate=250,
                            checklist_template_id=office_template.id)
        addon_windows = Service(name="Interior Window Cleaning", is_addon=True, base_rate=45)
        addon_carpet = Service(name="Carpet Shampooing", is_addon=True, base_rate=80)
        addon_fridge = Service(name="Refrigerator/Kitchen Deep Clean", is_addon=True, base_rate=35)
        for s in [svc_standard, svc_medical, svc_deep, addon_windows, addon_carpet, addon_fridge]:
            db.add(s)
        db.flush()

        # --- Owner, manager, employees ----------------------------------------
        owner = User(email="owner@cleanflow.demo", hashed_password=hash_password("Demo1234!"),
                     full_name="Alex Rivera", role=UserRole.OWNER)
        manager = User(email="manager@cleanflow.demo", hashed_password=hash_password("Demo1234!"),
                       full_name="Jordan Blake", role=UserRole.MANAGER)
        db.add_all([owner, manager])

        employees_data = [
            ("Maria Gonzalez", "maria@cleanflow.demo", ["floors", "windows"], 19.5),
            ("James Carter", "james@cleanflow.demo", ["medical-grade", "floors"], 21.0),
            ("Priya Patel", "priya@cleanflow.demo", ["carpets", "windows"], 20.0),
            ("Devon Brooks", "devon@cleanflow.demo", ["floors", "supplies"], 18.5),
        ]
        employees = []
        default_availability = {d: [["08:00", "17:00"]] for d in ["MON", "TUE", "WED", "THU", "FRI"]}
        for name, email, skills, rate in employees_data:
            emp = Employee(full_name=name, email=email, phone="(555) 555-0100", hourly_rate=rate,
                            skills=skills, availability=default_availability)
            db.add(emp)
            db.flush()
            employees.append(emp)
        # Give the first employee ("Maria") a portal login for the demo account
        maria_user = User(email="employee@cleanflow.demo", hashed_password=hash_password("Demo1234!"),
                           full_name=employees[0].full_name, role=UserRole.EMPLOYEE, employee_id=employees[0].id)
        db.add(maria_user)
        db.flush()

        # --- Leads -------------------------------------------------------------
        lead_specs = [
            ("Downtown Legal Group", "Sam Whitfield", "sam@downtownlegal.demo", PropertyType.OFFICE, 4200, 3, 2, LeadStatus.NEW, LeadSource.WEBSITE),
            ("Riverside Dental", "Dana Kim", "dana@riversidedental.demo", PropertyType.MEDICAL, 2100, 4, 1, LeadStatus.CONTACTED, LeadSource.PHONE),
            ("Metro Fitness Studio", "Chris Lee", "chris@metrofitness.demo", PropertyType.RETAIL, 5200, 3, 1, LeadStatus.QUALIFIED, LeadSource.REFERRAL),
            ("Sunridge Warehouse", "Pat Nguyen", "pat@sunridge.demo", PropertyType.WAREHOUSE, 15000, 2, 1, LeadStatus.NEW, LeadSource.WEBSITE),
            ("Blue Oak Cafe", "Taylor Reed", "taylor@blueoak.demo", PropertyType.RESTAURANT, 1800, 2, 1, LeadStatus.LOST, LeadSource.WALK_IN),
        ]
        leads = []
        for company, contact, email, ptype, sqft, baths, floors, status, source in lead_specs:
            lead = Lead(
                reference_number=next_reference(db, "lead"), contact_name=contact, company_name=company, email=email,
                phone="(555) 555-0111", address_line1="123 Business Ave", city="Austin", state="TX", zip_code="78701",
                property_type=ptype, square_footage=sqft, bathrooms=baths, floors=floors,
                frequency=CleaningFrequency.WEEKLY, requested_services=["Standard Commercial Cleaning"],
                source=source, status=status, estimated_value=sqft * 0.08,
            )
            db.add(lead)
            leads.append(lead)
        db.flush()

        # --- Demo customer walking the FULL flow (the one used in the scripted demo) ---
        demo_lead = Lead(
            reference_number=next_reference(db, "lead"), contact_name="Morgan Ellis", company_name="Ellis & Co. Consulting",
            email="customer@cleanflow.demo", phone="(555) 555-0199", address_line1="800 Commerce St", city="Austin",
            state="TX", zip_code="78702", property_type=PropertyType.OFFICE, square_footage=3000, bathrooms=3, floors=2,
            frequency=CleaningFrequency.WEEKLY, requested_services=["Standard Commercial Cleaning"],
            source=LeadSource.WEBSITE, status=LeadStatus.QUOTED, estimated_value=3000 * 0.08,
        )
        db.add(demo_lead)
        db.flush()

        demo_customer = Customer(company_name="Ellis & Co. Consulting", contact_name="Morgan Ellis",
                                  email="customer@cleanflow.demo", phone="(555) 555-0199",
                                  billing_address="800 Commerce St, Austin, TX 78702")
        db.add(demo_customer)
        db.flush()
        demo_lead.converted_customer_id = demo_customer.id

        demo_property = Property(customer_id=demo_customer.id, label="Ellis & Co. HQ", address_line1="800 Commerce St",
                                  city="Austin", state="TX", zip_code="78702", property_type=PropertyType.OFFICE,
                                  square_footage=3000, bathrooms=3, floors=2)
        db.add(demo_property)
        db.flush()

        demo_customer_user = User(email="customer@cleanflow.demo", hashed_password=hash_password("Demo1234!"),
                                   full_name="Morgan Ellis", role=UserRole.CUSTOMER, customer_id=demo_customer.id)
        db.add(demo_customer_user)

        calc = calculate_quote_price(db, QuoteCalculationInput(
            property_type=PropertyType.OFFICE, square_footage=3000, bathrooms=3, floors=2,
            frequency=CleaningFrequency.WEEKLY, addon_service_ids=[addon_fridge.id], has_special_conditions=False,
        ))
        demo_quote = Quote(
            reference_number=next_reference(db, "quote"), lead_id=demo_lead.id, customer_id=demo_customer.id,
            property_id=demo_property.id, property_type=PropertyType.OFFICE, square_footage=3000, bathrooms=3,
            floors=2, frequency=CleaningFrequency.WEEKLY, has_special_conditions="false",
            addon_service_ids=[addon_fridge.id], pricing_breakdown=calc.as_dict(), subtotal=calc.subtotal,
            total=calc.total, status=QuoteStatus.ACCEPTED, valid_until=now + timedelta(days=14),
            terms="Net 15. Cancel with 30 days notice.", sent_at=now - timedelta(days=3),
            viewed_at=now - timedelta(days=2), responded_at=now - timedelta(days=1), created_by_user_id=manager.id,
        )
        db.add(demo_quote)
        db.flush()
        db.add(QuoteItem(quote_id=demo_quote.id, service_id=svc_standard.id, description=svc_standard.name,
                          is_addon="false", amount=next(i["amount"] for i in calc.as_dict()["line_items"] if i["label"] == "Base service")))
        db.add(QuoteItem(quote_id=demo_quote.id, service_id=addon_fridge.id, description=addon_fridge.name,
                          is_addon="true", amount=addon_fridge.base_rate))
        db.flush()

        from app.contracts.service import activate_contract_from_accepted_quote
        demo_contract = activate_contract_from_accepted_quote(db, demo_quote, manager)
        db.flush()
        # Backdate the contract slightly so it has real history for the demo
        demo_contract.start_date = now - timedelta(days=21)
        demo_contract.created_at = now - timedelta(days=21)
        if demo_contract.schedule:
            demo_contract.schedule.start_date = now - timedelta(days=21)
            demo_contract.schedule.last_generated_through = now - timedelta(days=21)
            generate_jobs_for_schedule(db, demo_contract.schedule, manager)
        db.flush()

        # Assign employees + progress some historical jobs to completed with proof
        demo_jobs = db.query(Job).filter(Job.contract_id == demo_contract.id).order_by(Job.scheduled_start).all()
        for j in demo_jobs:
            db.add(JobAssignment(job_id=j.id, employee_id=employees[0].id, is_lead=True))
        db.flush()

        past_jobs = [j for j in demo_jobs if j.scheduled_start < now]
        for j in past_jobs:
            j.status = JobStatus.COMPLETED
            j.check_in_at = j.scheduled_start
            j.check_out_at = j.scheduled_start + timedelta(minutes=85)
            j.completed_at = j.check_out_at
            for item in j.checklist_items:
                item.is_completed = True
                item.completed_at = j.completed_at
            db.add(JobPhoto(job_id=j.id, uploaded_by_employee_id=employees[0].id, photo_type=PhotoType.BEFORE,
                             storage_key="demo/before-placeholder.jpg", caption="Before service"))
            db.add(JobPhoto(job_id=j.id, uploaded_by_employee_id=employees[0].id, photo_type=PhotoType.AFTER,
                             storage_key="demo/after-placeholder.jpg", caption="After service"))
        db.flush()

        # Leave the next upcoming job assigned-but-not-started so the demo can
        # walk through check-in -> checklist -> photos -> check-out live.
        future_jobs = [j for j in demo_jobs if j.scheduled_start >= now]
        # Leave exactly one job UNASSIGNED to populate "Attention Required"
        if len(future_jobs) >= 2:
            db.query(JobAssignment).filter(JobAssignment.job_id == future_jobs[-1].id).delete()

        # Invoice + payment for the first completed job
        if past_jobs:
            from app.invoices.service import create_invoice_from_job, send_invoice
            from app.payments.service import record_payment
            inv = create_invoice_from_job(db, past_jobs[0], due_in_days=15, tax_rate_percent=0.0, actor=manager)
            db.flush()
            send_invoice(db, inv, manager)

            class _Pay:
                amount = inv.total
                method = PaymentMethod.CREDIT_CARD
                paid_at = now - timedelta(days=1)
                reference = "CARD-4471"
                notes = "Paid via card on file"
                allow_overpayment = False

            record_payment(db, inv, _Pay(), manager)

            if len(past_jobs) > 1:
                inv2 = create_invoice_from_job(db, past_jobs[1], due_in_days=15, tax_rate_percent=0.0, actor=manager)
                send_invoice(db, inv2, manager)
                inv2.due_date = now - timedelta(days=3)  # force overdue for the Attention Required demo

            db.add(Feedback(job_id=past_jobs[0].id, customer_id=demo_customer.id, rating=5,
                             comment="Great job, office looked spotless!"))

        db.commit()

        # --- Some additional standalone customers/contracts for a populated feel ---
        extra_customers = [
            ("Northgate Realty", "Casey Morgan", "casey@northgate.demo", PropertyType.OFFICE, 2200, 2, 1),
            ("Lakeside Family Medicine", "Robin Torres", "robin@lakesidemed.demo", PropertyType.MEDICAL, 3100, 5, 1),
            ("Union Square Retail", "Jamie Foster", "jamie@unionsquare.demo", PropertyType.RETAIL, 4000, 2, 1),
        ]
        for company, contact, email, ptype, sqft, baths, floors in extra_customers:
            cust = Customer(company_name=company, contact_name=contact, email=email, phone="(555) 555-0120",
                             billing_address="200 Market St, Austin, TX 78703")
            db.add(cust)
            db.flush()
            prop = Property(customer_id=cust.id, label="Main Location", address_line1="200 Market St", city="Austin",
                             state="TX", zip_code="78703", property_type=ptype, square_footage=sqft, bathrooms=baths,
                             floors=floors)
            db.add(prop)
            db.flush()
            calc2 = calculate_quote_price(db, QuoteCalculationInput(
                property_type=ptype, square_footage=sqft, bathrooms=baths, floors=floors,
                frequency=CleaningFrequency.WEEKLY, addon_service_ids=[],
            ))
            q = Quote(
                reference_number=next_reference(db, "quote"), customer_id=cust.id, property_id=prop.id,
                property_type=ptype, square_footage=sqft, bathrooms=baths, floors=floors,
                frequency=CleaningFrequency.WEEKLY, has_special_conditions="false", addon_service_ids=[],
                pricing_breakdown=calc2.as_dict(), subtotal=calc2.subtotal, total=calc2.total,
                status=QuoteStatus.ACCEPTED, valid_until=now + timedelta(days=14),
                sent_at=now - timedelta(days=10), responded_at=now - timedelta(days=9), created_by_user_id=manager.id,
            )
            db.add(q)
            db.flush()
            db.add(QuoteItem(quote_id=q.id, service_id=svc_standard.id, description=svc_standard.name, is_addon="false",
                              amount=calc2.subtotal))
            db.flush()
            c = activate_contract_from_accepted_quote(db, q, manager)
            c.start_date = now - timedelta(days=14)
            if c.schedule:
                c.schedule.start_date = now - timedelta(days=14)
                c.schedule.last_generated_through = now - timedelta(days=14)
                generate_jobs_for_schedule(db, c.schedule, manager)
            db.flush()
            jobs_c = db.query(Job).filter(Job.contract_id == c.id).all()
            for j in jobs_c:
                emp = employees[hash(j.id) % len(employees)]
                db.add(JobAssignment(job_id=j.id, employee_id=emp.id))
                if j.scheduled_start < now:
                    j.status = JobStatus.COMPLETED
                    j.check_in_at = j.scheduled_start
                    j.check_out_at = j.scheduled_start + timedelta(minutes=80)
                    j.completed_at = j.check_out_at
                    for item in j.checklist_items:
                        item.is_completed = True
            db.commit()

        print("\nSeed complete!\n")
        print("Demo accounts (all passwords: Demo1234!):")
        print("  Owner:    owner@cleanflow.demo")
        print("  Manager:  manager@cleanflow.demo")
        print("  Employee: employee@cleanflow.demo")
        print("  Customer: customer@cleanflow.demo")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    wipe_and_create()
    seed()
