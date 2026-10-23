from sqlalchemy import Column, String, Float, Integer, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin, SoftDeleteMixin
from app.common.enums import PropertyType


class Customer(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "customers"

    company_name = Column(String(255), nullable=True)
    contact_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(50), nullable=False)
    billing_address = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    # Set once a lead converts / customer accepts a quote; nullable because
    # a Customer can exist before a portal login is provisioned.
    user = relationship("User", back_populates="customer", uselist=False, foreign_keys="User.customer_id")

    properties = relationship("Property", back_populates="customer", cascade="all, delete-orphan")
    contracts = relationship("Contract", back_populates="customer")
    quotes = relationship("Quote", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")

    @property
    def display_name(self) -> str:
        return self.company_name or self.contact_name


class Property(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "properties"

    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)

    label = Column(String(255), nullable=False)  # e.g. "Main Office - Downtown"
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(120), nullable=False)
    state = Column(String(60), nullable=False)
    zip_code = Column(String(20), nullable=False)

    property_type = Column(Enum(PropertyType), nullable=False, default=PropertyType.OFFICE)
    square_footage = Column(Integer, nullable=False)
    bathrooms = Column(Integer, nullable=False, default=1)
    floors = Column(Integer, nullable=False, default=1)
    access_notes = Column(Text, nullable=True)  # gate codes, parking, contact on-site, etc.

    customer = relationship("Customer", back_populates="properties")
    jobs = relationship("Job", back_populates="site")

    @property
    def full_address(self) -> str:
        line2 = f" {self.address_line2}" if self.address_line2 else ""
        return f"{self.address_line1}{line2}, {self.city}, {self.state} {self.zip_code}"
