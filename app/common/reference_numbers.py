"""
Human-facing reference numbers (QT-1024, JOB-0087, INV-2031, ...) are
generated from a small counters table rather than random strings, so
numbers are sequential, gap-free-ish, and easy for staff/customers to
say out loud on the phone.
"""
from sqlalchemy import Column, String, Integer
from sqlalchemy.orm import Session

from app.config.database import Base


class ReferenceCounter(Base):
    __tablename__ = "reference_counters"

    prefix = Column(String(10), primary_key=True)
    last_value = Column(Integer, nullable=False, default=1000)


PREFIXES = {
    "lead": "LD",
    "quote": "QT",
    "contract": "CT",
    "job": "JOB",
    "invoice": "INV",
}


def next_reference(db: Session, entity: str) -> str:
    prefix = PREFIXES[entity]
    counter = db.query(ReferenceCounter).filter_by(prefix=prefix).first()
    if not counter:
        counter = ReferenceCounter(prefix=prefix, last_value=1000)
        db.add(counter)
        db.flush()
    counter.last_value += 1
    db.flush()
    return f"{prefix}-{counter.last_value}"
