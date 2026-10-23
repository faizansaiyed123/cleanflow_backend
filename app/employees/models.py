from sqlalchemy import Column, String, Float, Integer, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin, SoftDeleteMixin


class Employee(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "employees"

    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    phone = Column(String(50), nullable=False)
    hourly_rate = Column(Float, nullable=False, default=18.0)
    skills = Column(JSON, nullable=False, default=list)  # e.g. ["floors", "medical-grade", "windows"]
    profile_photo_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # availability: {"MON": [["08:00","17:00"]], "TUE": [...], ...}
    availability = Column(JSON, nullable=False, default=dict)

    user = relationship("User", back_populates="employee", uselist=False, foreign_keys="User.employee_id")
    assignments = relationship("JobAssignment", back_populates="employee")
