from sqlalchemy import Column, String, Float, Boolean, ForeignKey, Text, Integer
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.common.mixins import UUIDPKMixin, TimestampMixin, SoftDeleteMixin


class Service(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """A sellable cleaning service, e.g. 'Standard Office Cleaning',
    'Deep Clean', 'Window Cleaning (add-on)'."""

    __tablename__ = "services"

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_addon = Column(Boolean, default=False, nullable=False)
    base_rate = Column(Float, nullable=False, default=0.0)  # used by the pricing engine as a fallback/base

    checklist_template_id = Column(String(36), ForeignKey("checklist_templates.id"), nullable=True)
    checklist_template = relationship("ChecklistTemplate", back_populates="services")


class ChecklistTemplate(Base, UUIDPKMixin, TimestampMixin):
    """Reusable checklist attached to a service. When a job is generated,
    its items are copied onto the Job as JobChecklistItem rows so that
    editing the template later never changes a job already in progress
    or already completed."""

    __tablename__ = "checklist_templates"

    name = Column(String(255), nullable=False)
    services = relationship("Service", back_populates="checklist_template")
    items = relationship("ChecklistTemplateItem", back_populates="template", cascade="all, delete-orphan",
                          order_by="ChecklistTemplateItem.sort_order")


class ChecklistTemplateItem(Base, UUIDPKMixin):
    __tablename__ = "checklist_template_items"

    template_id = Column(String(36), ForeignKey("checklist_templates.id"), nullable=False)
    label = Column(String(255), nullable=False)
    is_required = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    template = relationship("ChecklistTemplate", back_populates="items")
