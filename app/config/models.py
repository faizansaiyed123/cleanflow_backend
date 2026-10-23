from sqlalchemy import Column, String, Float, Text, JSON

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class CompanySetting(Base, UUIDPKMixin, TimestampMixin):
    """Single-row settings table (one company per deployment for this
    portfolio project). A multi-tenant version would add a company_id
    foreign key across every table; kept out here to keep the schema
    readable, per the brief's explicit request to avoid overcomplication."""

    __tablename__ = "company_settings"

    company_name = Column(String(255), nullable=False, default="CleanFlow Cleaning Co.")
    logo_url = Column(String(500), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(String(500), nullable=True)
    business_hours = Column(JSON, nullable=False, default=dict)
    currency = Column(String(10), nullable=False, default="USD")
    default_tax_rate_percent = Column(Float, nullable=False, default=0.0)
    invoice_due_days = Column(Float, nullable=False, default=15)
    quote_validity_days = Column(Float, nullable=False, default=14)
    notification_settings = Column(JSON, nullable=False, default=dict)
