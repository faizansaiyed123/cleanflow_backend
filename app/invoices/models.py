from sqlalchemy import Column, String, Float, Enum, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import InvoiceStatus, InvoiceSourceType


class Invoice(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "invoices"

    reference_number = Column(String(20), unique=True, nullable=False, index=True)

    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    property_id = Column(String(36), ForeignKey("properties.id"), nullable=True)
    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=True)

    source_type = Column(Enum(InvoiceSourceType), nullable=False, default=InvoiceSourceType.MANUAL)
    billing_period_start = Column(DateTime(), nullable=True)
    billing_period_end = Column(DateTime(), nullable=True)

    subtotal = Column(Float, nullable=False, default=0.0)
    discount_amount = Column(Float, nullable=False, default=0.0)
    tax_amount = Column(Float, nullable=False, default=0.0)
    total = Column(Float, nullable=False, default=0.0)
    amount_paid = Column(Float, nullable=False, default=0.0)

    status = Column(Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.DRAFT, index=True)
    due_date = Column(DateTime(), nullable=False)
    sent_at = Column(DateTime(), nullable=True)
    voided_at = Column(DateTime(), nullable=True)
    notes = Column(Text, nullable=True)

    customer = relationship("Customer", back_populates="invoices")
    site = relationship("Property")
    contract = relationship("Contract")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def balance_due(self) -> float:
        return round(self.total - self.amount_paid, 2)


class InvoiceItem(Base, UUIDPKMixin):
    __tablename__ = "invoice_items"

    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=True)
    description = Column(String(255), nullable=False)
    amount = Column(Float, nullable=False)

    invoice = relationship("Invoice", back_populates="items")
    job = relationship("Job", back_populates="invoice_items")
