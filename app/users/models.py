from sqlalchemy import Column, String, Boolean, Enum, ForeignKey
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin
from app.common.enums import UserRole


class User(Base, UUIDPKMixin, TimestampMixin):
    """
    Every login (owner, manager, employee, customer) is a User row.
    Role-specific data (Employee, Customer profiles) lives in their own
    tables and links back via user_id — this keeps auth concerns (email,
    password, role, active flag) separate from domain profile concerns.
    """

    __tablename__ = "users"

    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Nullable FKs: only populated for the matching role
    employee_id = Column(String(36), ForeignKey("employees.id"), nullable=True, unique=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True, unique=True)

    employee = relationship("Employee", back_populates="user", foreign_keys=[employee_id])
    customer = relationship("Customer", back_populates="user", foreign_keys=[customer_id])
