from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class Feedback(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "feedback"

    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, unique=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)

    job = relationship("Job", back_populates="feedback")
    customer = relationship("Customer")
