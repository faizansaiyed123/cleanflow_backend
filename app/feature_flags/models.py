from sqlalchemy import Column, String, Boolean, Text
from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin


class FeatureFlag(Base, UUIDPKMixin, TimestampMixin):
    """Simple boolean feature flags, toggleable by the owner at runtime
    without a deploy -- the standard mechanism for progressive rollout
    and for gating a feature that changes business behavior (like
    auto-invoicing) behind explicit opt-in."""

    __tablename__ = "feature_flags"

    key = Column(String(100), unique=True, nullable=False, index=True)
    is_enabled = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
