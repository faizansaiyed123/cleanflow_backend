from sqlalchemy import Column, String, ForeignKey, JSON

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    actor_role = Column(String(20), nullable=True)
    action = Column(String(100), nullable=False, index=True)  # e.g. "quote.accepted"
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(String(36), nullable=False, index=True)
    previous_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
