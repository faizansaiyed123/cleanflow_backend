"""
PDF generation for quotes and invoices, using reportlab. Kept as a
standalone module (rather than living inside quotes/ or invoices/) since
it's a cross-cutting document-rendering concern, not business logic.
"""
import io
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from app.quotes.models import Quote
from app.invoices.models import Invoice
from app.customers.models import Customer, Property
from app.config.models import CompanySetting

MOSS = colors.HexColor('#2f6b52')
INK = colors.HexColor('#14231f')


def _company_header(company: CompanySetting | None):
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CompanyTitle', parent=styles['Title'], textColor=MOSS, fontSize=20)
    name = company.company_name if company else "CleanFlow Commercial Cleaning Co."
    lines = [Paragraph(name, title_style)]
    if company:
        contact_bits = [company.address, company.phone, company.email]
        contact = " · ".join([c for c in contact_bits if c])
        if contact:
            lines.append(Paragraph(contact, styles['Normal']))
    return lines


def generate_quote_pdf(quote: Quote, customer: Customer | None, property_: Property | None,
                        company: CompanySetting | None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    elements = []

    elements += _company_header(company)
    elements.append(Spacer(1, 16))
    elements.append(Paragraph(f"Quote {quote.reference_number}", styles['Heading1']))
    elements.append(Paragraph(f"Status: {quote.status.value}  ·  Valid until {quote.valid_until.strftime('%B %d, %Y')}",
                               styles['Normal']))
    elements.append(Spacer(1, 12))

    if customer:
        elements.append(Paragraph(f"<b>Prepared for:</b> {customer.display_name}", styles['Normal']))
        elements.append(Paragraph(f"{customer.email} · {customer.phone}", styles['Normal']))
    if property_:
        elements.append(Paragraph(f"<b>Property:</b> {property_.label} — {property_.full_address}", styles['Normal']))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(f"Property type: {quote.property_type.value} · "
                               f"{quote.square_footage} sq ft · {quote.bathrooms} bathrooms · "
                               f"{quote.floors} floor(s) · {quote.frequency.value} service", styles['Normal']))
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("Why this price?", styles['Heading2']))
    data = [["Line Item", "Amount"]]
    for li in quote.pricing_breakdown["line_items"]:
        amt = li["amount"]
        data.append([li["label"], f"-${abs(amt):,.2f}" if amt < 0 else f"${amt:,.2f}"])
    data.append(["Total", f"${quote.total:,.2f}"])

    table = Table(data, colWidths=[4.2 * inch, 1.8 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), MOSS),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, INK),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e4e0d4')),
    ]))
    elements.append(table)

    if quote.terms:
        elements.append(Spacer(1, 16))
        elements.append(Paragraph("Terms", styles['Heading3']))
        elements.append(Paragraph(quote.terms, styles['Normal']))
    if quote.notes:
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Notes", styles['Heading3']))
        elements.append(Paragraph(quote.notes, styles['Normal']))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Generated {datetime.utcnow().strftime('%B %d, %Y')}", styles['Normal']))

    doc.build(elements)
    return buf.getvalue()


def generate_invoice_pdf(invoice: Invoice, customer: Customer | None, property_: Property | None,
                          company: CompanySetting | None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    elements = []

    elements += _company_header(company)
    elements.append(Spacer(1, 16))
    elements.append(Paragraph(f"Invoice {invoice.reference_number}", styles['Heading1']))
    elements.append(Paragraph(f"Status: {invoice.status.value}  ·  Due {invoice.due_date.strftime('%B %d, %Y')}",
                               styles['Normal']))
    elements.append(Spacer(1, 12))

    if customer:
        elements.append(Paragraph(f"<b>Bill to:</b> {customer.display_name}", styles['Normal']))
        elements.append(Paragraph(f"{customer.email} · {customer.phone}", styles['Normal']))
    if property_:
        elements.append(Paragraph(f"<b>Property:</b> {property_.label} — {property_.full_address}", styles['Normal']))
    elements.append(Spacer(1, 16))

    data = [["Description", "Amount"]]
    for item in invoice.items:
        data.append([item.description, f"${item.amount:,.2f}"])
    data.append(["Subtotal", f"${invoice.subtotal:,.2f}"])
    if invoice.discount_amount:
        data.append(["Discount", f"-${invoice.discount_amount:,.2f}"])
    if invoice.tax_amount:
        data.append(["Tax", f"${invoice.tax_amount:,.2f}"])
    data.append(["Total", f"${invoice.total:,.2f}"])
    data.append(["Amount Paid", f"${invoice.amount_paid:,.2f}"])
    data.append(["Balance Due", f"${invoice.balance_due:,.2f}"])

    table = Table(data, colWidths=[4.2 * inch, 1.8 * inch])
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), MOSS),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e4e0d4')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, INK),
    ]
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)

    if invoice.notes:
        elements.append(Spacer(1, 16))
        elements.append(Paragraph("Notes", styles['Heading3']))
        elements.append(Paragraph(invoice.notes, styles['Normal']))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Generated {datetime.utcnow().strftime('%B %d, %Y')}", styles['Normal']))

    doc.build(elements)
    return buf.getvalue()
