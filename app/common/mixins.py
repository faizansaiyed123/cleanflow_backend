import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Boolean, String
from sqlalchemy.orm import declared_attr


def utcnow():
    return datetime.utcnow()


class UUIDPKMixin:
    """Every table uses a UUID string primary key. UUIDs avoid leaking
    sequential-ID business info (e.g. how many customers/invoices exist)
    to anyone who can see one record's id, and they merge safely if the
    company's data is ever migrated between environments."""

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class TimestampMixin:
    created_at = Column(DateTime(), default=utcnow, nullable=False)
    updated_at = Column(DateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    """Archive instead of hard-delete so historical reporting (invoices,
    completed jobs, revenue history) never breaks when a customer,
    employee, or service is removed from active use."""

    is_archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(), nullable=True)
