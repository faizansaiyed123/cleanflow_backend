from sqlalchemy import Column, String, Float, Enum, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import ContractStatus, CleaningFrequency


class Contract(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "contracts"

    reference_number = Column(String(20), unique=True, nullable=False, index=True)

    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    property_id = Column(String(36), ForeignKey("properties.id"), nullable=False)
    originating_quote_id = Column(String(36), ForeignKey("quotes.id"), nullable=True, unique=True)

    start_date = Column(DateTime(), nullable=False)
    end_date = Column(DateTime(), nullable=True)  # null = open-ended / until cancelled
    frequency = Column(Enum(CleaningFrequency), nullable=False)
    monthly_value = Column(Float, nullable=False)

    terms = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(Enum(ContractStatus), nullable=False, default=ContractStatus.PENDING, index=True)

    paused_at = Column(DateTime(), nullable=True)
    cancelled_at = Column(DateTime(), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    # When a contract is renewed, the new contract points back at the old one.
    renewed_from_contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=True)

    customer = relationship("Customer", back_populates="contracts")
    site = relationship("Property")
    originating_quote = relationship("Quote", back_populates="contract")
    services = relationship("ContractService", back_populates="contract", cascade="all, delete-orphan")
    schedule = relationship("RecurringSchedule", back_populates="contract", uselist=False,
                             cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="contract")


class ContractService(Base, UUIDPKMixin):
    __tablename__ = "contract_services"

    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=False)
    service_id = Column(String(36), ForeignKey("services.id"), nullable=False)
    price = Column(Float, nullable=False)

    contract = relationship("Contract", back_populates="services")
    service = relationship("Service")
