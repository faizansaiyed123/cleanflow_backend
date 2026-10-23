from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.auth.deps import require_admin_or_manager, get_current_user
from app.users.models import User
from app.common.exceptions import NotFoundError
from app.audit.service import record_audit
from app.services.models import Service, ChecklistTemplate, ChecklistTemplateItem
from app.services.schemas import (
    ServiceCreate, ServiceUpdate, ServiceOut, ChecklistTemplateCreate, ChecklistTemplateOut,
)

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
def list_services(include_archived: bool = False, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    query = db.query(Service)
    if not include_archived:
        query = query.filter(Service.is_archived.is_(False))
    return query.order_by(Service.is_addon, Service.name).all()


@router.post("", response_model=ServiceOut, status_code=201)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin_or_manager)):
    service = Service(**payload.model_dump())
    db.add(service)
    db.flush()
    record_audit(db, current_user, "service.created", "Service", service.id, new_state=payload.model_dump(mode="json"))
    db.commit()
    db.refresh(service)
    return service


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(service_id: str, payload: ServiceUpdate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin_or_manager)):
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise NotFoundError("Service", service_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(service, field, value)
    record_audit(db, current_user, "service.updated", "Service", service.id, new_state=changes)
    db.commit()
    db.refresh(service)
    return service


@router.get("/checklist-templates", response_model=list[ChecklistTemplateOut])
def list_checklist_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ChecklistTemplate).options(joinedload(ChecklistTemplate.items)).all()


@router.post("/checklist-templates", response_model=ChecklistTemplateOut, status_code=201)
def create_checklist_template(payload: ChecklistTemplateCreate, db: Session = Depends(get_db),
                               current_user: User = Depends(require_admin_or_manager)):
    template = ChecklistTemplate(name=payload.name)
    db.add(template)
    db.flush()
    for item in payload.items:
        db.add(ChecklistTemplateItem(template_id=template.id, **item.model_dump()))
    record_audit(db, current_user, "checklist_template.created", "ChecklistTemplate", template.id)
    db.commit()
    db.refresh(template)
    return template
