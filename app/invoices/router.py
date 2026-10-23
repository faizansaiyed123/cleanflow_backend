from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.config.database import get_db
from app.auth.deps import get_current_user, require_financial_access
from app.users.models import User
from app.common.enums import UserRole, InvoiceStatus
from app.common.exceptions import NotFoundError, ForbiddenError
from app.invoices.models import Invoice
from app.invoices.schemas import ManualInvoiceCreate, InvoiceFromJobRequest, InvoiceOut
from app.invoices import service as invoice_service
from app.jobs.models import Job
from app.common.pagination import Page, paginate, apply_sort

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


def _get_invoice_or_404(db: Session, invoice_id: str) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise NotFoundError("Invoice", invoice_id)
    return invoice


class BulkSendRequest(BaseModel):
    invoice_ids: list[str]


@router.post("/bulk-send")
def bulk_send_invoices(payload: BulkSendRequest, db: Session = Depends(get_db),
                        current_user: User = Depends(require_financial_access)):
    results = {"sent": [], "failed": []}
    for inv_id in payload.invoice_ids:
        invoice = db.query(Invoice).filter(Invoice.id == inv_id).first()
        if not invoice:
            results["failed"].append({"invoice_id": inv_id, "reason": "not found"})
            continue
        try:
            invoice_service.send_invoice(db, invoice, current_user)
            results["sent"].append(inv_id)
        except Exception as exc:
            results["failed"].append({"invoice_id": inv_id, "reason": str(exc)})
    db.commit()
    return results


@router.get("", response_model=Page[InvoiceOut])
def list_invoices(status: InvoiceStatus | None = None, customer_id: str | None = None,
                   page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
                   sort_by: str = Query(default="created_at"), sort_dir: str = Query(default="desc"),
                   db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    invoice_service.refresh_overdue_status(db)
    db.commit()
    query = db.query(Invoice)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Invoice.customer_id == current_user.customer_id)
    elif current_user.role == UserRole.EMPLOYEE:
        raise ForbiddenError("Employees do not have access to financial data")
    elif customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    if status:
        query = query.filter(Invoice.status == status)
    query = apply_sort(query, Invoice, sort_by, sort_dir)
    items, total = paginate(query, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/export/csv")
def export_invoices_csv(status: InvoiceStatus | None = None, db: Session = Depends(get_db),
                         current_user: User = Depends(require_financial_access)):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    query = db.query(Invoice)
    if status:
        query = query.filter(Invoice.status == status)
    invoices = query.order_by(Invoice.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Reference", "Customer ID", "Status", "Subtotal", "Discount", "Tax", "Total", "Amount Paid",
                      "Balance Due", "Due Date", "Created At"])
    for i in invoices:
        writer.writerow([i.reference_number, i.customer_id, i.status.value, i.subtotal, i.discount_amount,
                          i.tax_amount, i.total, i.amount_paid, i.balance_due, i.due_date.isoformat(),
                          i.created_at.isoformat()])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=invoices.csv"})


@router.post("", response_model=InvoiceOut, status_code=201)
def create_manual_invoice(payload: ManualInvoiceCreate, db: Session = Depends(get_db),
                           current_user: User = Depends(require_financial_access)):
    invoice = invoice_service.create_manual_invoice(db, payload, current_user)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/from-job/{job_id}", response_model=InvoiceOut, status_code=201)
def create_invoice_from_job(job_id: str, payload: InvoiceFromJobRequest, db: Session = Depends(get_db),
                             current_user: User = Depends(require_financial_access)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise NotFoundError("Job", job_id)
    invoice = invoice_service.create_invoice_from_job(db, job, payload.due_in_days, payload.tax_rate_percent, current_user)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    invoice = _get_invoice_or_404(db, invoice_id)
    if current_user.role == UserRole.CUSTOMER and invoice.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this invoice")
    if current_user.role == UserRole.EMPLOYEE:
        raise ForbiddenError("Employees do not have access to financial data")
    return invoice


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.pdf_export.service import generate_invoice_pdf
    from app.customers.models import Customer, Property
    from app.config.models import CompanySetting

    invoice = _get_invoice_or_404(db, invoice_id)
    if current_user.role == UserRole.CUSTOMER and invoice.customer_id != current_user.customer_id:
        raise ForbiddenError("You do not have access to this invoice")
    if current_user.role == UserRole.EMPLOYEE:
        raise ForbiddenError("Employees do not have access to financial data")

    customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    property_ = db.query(Property).filter(Property.id == invoice.property_id).first() if invoice.property_id else None
    company = db.query(CompanySetting).first()

    pdf_bytes = generate_invoice_pdf(invoice, customer, property_, company)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{invoice.reference_number}.pdf"'
    })


@router.post("/{invoice_id}/send", response_model=InvoiceOut)
def send_invoice(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_financial_access)):
    invoice = _get_invoice_or_404(db, invoice_id)
    invoice_service.send_invoice(db, invoice, current_user)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void_invoice(invoice_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_financial_access)):
    invoice = _get_invoice_or_404(db, invoice_id)
    invoice_service.void_invoice(db, invoice, current_user)
    db.commit()
    db.refresh(invoice)
    return invoice
