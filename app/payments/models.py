from sqlalchemy import Column, String, Float, Enum, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import PaymentMethod


class Payment(Base, UUIDPKMixin, TimestampMixin):
    """
    Manual payment recording for the MVP (check, cash, card-on-file,
    ACH). The model intentionally mirrors what a Stripe PaymentIntent
    would need (amount, method, external reference) so a future gateway
    integration only has to add a webhook handler that calls the same
    `record_payment` service function -- no schema change required.
    """

    __tablename__ = "payments"

    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    method = Column(Enum(PaymentMethod), nullable=False)
    paid_at = Column(DateTime(), nullable=False)
    reference = Column(String(255), nullable=True)  # check #, transaction id, etc.
    notes = Column(Text, nullable=True)
    recorded_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    invoice = relationship("Invoice", back_populates="payments")
