from sqlalchemy import Column, String, Integer, Float, Enum, ForeignKey, Text, DateTime, JSON
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import LeadSource, LeadStatus, PropertyType, CleaningFrequency


class Lead(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "leads"

    reference_number = Column(String(20), unique=True, nullable=False, index=True)

    contact_name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)

    address_line1 = Column(String(255), nullable=True)
    city = Column(String(120), nullable=True)
    state = Column(String(60), nullable=True)
    zip_code = Column(String(20), nullable=True)

    property_type = Column(Enum(PropertyType), nullable=False, default=PropertyType.OFFICE)
    square_footage = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    floors = Column(Integer, nullable=True)
    frequency = Column(Enum(CleaningFrequency), nullable=True)

    requested_services = Column(JSON, nullable=False, default=list)  # list of service names/ids
    requested_addons = Column(JSON, nullable=False, default=list)
    preferred_start_date = Column(DateTime(), nullable=True)
    preferred_time = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)

    source = Column(Enum(LeadSource), nullable=False, default=LeadSource.WEBSITE)
    status = Column(Enum(LeadStatus), nullable=False, default=LeadStatus.NEW, index=True)
    estimated_value = Column(Float, nullable=True)
    last_contacted_at = Column(DateTime(), nullable=True)

    # Set once converted to an actual customer record
    converted_customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True)

    quotes = relationship("Quote", back_populates="lead")
