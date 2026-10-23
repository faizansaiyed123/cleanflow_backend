from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.auth.deps import require_owner
from app.users.models import User
from app.common.exceptions import NotFoundError, ValidationAppError
from app.audit.service import record_audit
from app.webhooks.models import WebhookEndpoint, WebhookDelivery
from app.webhooks.schemas import (
    WebhookEndpointCreate, WebhookEndpointOut, WebhookEndpointCreatedOut, WebhookDeliveryOut, ALL_EVENT_TYPES,
)
from app.webhooks.service import generate_secret, redeliver

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/event-types")
def list_event_types(current_user: User = Depends(require_owner)):
    return {"event_types": ALL_EVENT_TYPES}


@router.get("/endpoints", response_model=list[WebhookEndpointOut])
def list_endpoints(db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    return db.query(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc()).all()


@router.post("/endpoints", response_model=WebhookEndpointCreatedOut, status_code=201)
def create_endpoint(payload: WebhookEndpointCreate, db: Session = Depends(get_db),
                     current_user: User = Depends(require_owner)):
    invalid = set(payload.subscribed_events) - set(ALL_EVENT_TYPES)
    if invalid:
        raise ValidationAppError(f"Unknown event type(s): {', '.join(invalid)}")
    if not payload.url.startswith("https://") and not payload.url.startswith("http://"):
        raise ValidationAppError("Webhook URL must start with http:// or https://")

    secret = generate_secret()
    endpoint = WebhookEndpoint(url=payload.url, secret=secret, subscribed_events=payload.subscribed_events,
                                description=payload.description)
    db.add(endpoint)
    db.flush()
    record_audit(db, current_user, "webhook_endpoint.created", "WebhookEndpoint", endpoint.id,
                 new_state={"url": payload.url, "events": payload.subscribed_events})
    db.commit()
    db.refresh(endpoint)
    result = WebhookEndpointCreatedOut.model_validate(endpoint)
    result.secret = secret
    return result


@router.post("/endpoints/{endpoint_id}/deactivate", response_model=WebhookEndpointOut)
def deactivate_endpoint(endpoint_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    endpoint = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id).first()
    if not endpoint:
        raise NotFoundError("WebhookEndpoint", endpoint_id)
    endpoint.is_active = False
    record_audit(db, current_user, "webhook_endpoint.deactivated", "WebhookEndpoint", endpoint.id)
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.get("/endpoints/{endpoint_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(endpoint_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    return (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(100)
        .all()
    )


@router.post("/deliveries/{delivery_id}/redeliver", response_model=WebhookDeliveryOut)
def retry_delivery(delivery_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_owner)):
    """Manually resurrect a dead-lettered delivery -- e.g. after the
    receiving team confirms their endpoint is back up."""
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not delivery:
        raise NotFoundError("WebhookDelivery", delivery_id)
    redeliver(db, delivery)
    record_audit(db, current_user, "webhook_delivery.redelivered", "WebhookDelivery", delivery.id)
    db.commit()
    db.refresh(delivery)
    return delivery
