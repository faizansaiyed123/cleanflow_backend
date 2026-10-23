from sqlalchemy import Column, String, Float, Integer, Enum, ForeignKey, Text, DateTime, JSON
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import QuoteStatus, PropertyType, CleaningFrequency


class Quote(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "quotes"

    reference_number = Column(String(20), unique=True, nullable=False, index=True)

    lead_id = Column(String(36), ForeignKey("leads.id"), nullable=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True, index=True)
    property_id = Column(String(36), ForeignKey("properties.id"), nullable=True)

    # Denormalized property specs captured at quote time. A Quote may be
    # generated before a Property record exists (straight from a lead),
    # so these fields make the quote self-contained and explainable even
    # if the property details change later.
    property_type = Column(Enum(PropertyType), nullable=False)
    square_footage = Column(Integer, nullable=False)
    bathrooms = Column(Integer, nullable=False)
    floors = Column(Integer, nullable=False)
    frequency = Column(Enum(CleaningFrequency), nullable=False)
    has_special_conditions = Column(String(5), default="false")

    addon_service_ids = Column(JSON, nullable=False, default=list)
    manual_discount_percent = Column(Float, nullable=False, default=0.0)
    manual_discount_reason = Column(String(255), nullable=True)

    # Snapshot of the pricing engine output at the moment the quote was
    # generated -- this is what "Why this price?" renders. It intentionally
    # never changes even if pricing rules change afterward.
    pricing_breakdown = Column(JSON, nullable=False)
    subtotal = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False, default=0.0)
    total = Column(Float, nullable=False)

    status = Column(Enum(QuoteStatus), nullable=False, default=QuoteStatus.DRAFT, index=True)
    valid_until = Column(DateTime(), nullable=False)
    terms = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    sent_at = Column(DateTime(), nullable=True)
    viewed_at = Column(DateTime(), nullable=True)
    responded_at = Column(DateTime(), nullable=True)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    cloned_from_quote_id = Column(String(36), ForeignKey("quotes.id"), nullable=True)

    lead = relationship("Lead", back_populates="quotes")
    customer = relationship("Customer", back_populates="quotes")
    contract = relationship("Contract", back_populates="originating_quote", uselist=False)
    items = relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan")


class QuoteItem(Base, UUIDPKMixin):
    """The services included on the quote (primary service + add-ons),
    used to seed ContractService rows once the quote is accepted."""

    __tablename__ = "quote_items"

    quote_id = Column(String(36), ForeignKey("quotes.id"), nullable=False)
    service_id = Column(String(36), ForeignKey("services.id"), nullable=False)
    description = Column(String(255), nullable=True)
    is_addon = Column(String(5), default="false")
    amount = Column(Float, nullable=False)

    quote = relationship("Quote", back_populates="items")
    service = relationship("Service")
