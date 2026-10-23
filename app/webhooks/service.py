"""
Outbound webhook delivery: HMAC-signed payloads, exponential backoff
with jitter, and a dead-letter state after max attempts. This mirrors
how Stripe/GitHub webhooks work, implemented against nothing but the
receiver's own HTTP endpoint -- no third-party service involved.
"""
import hashlib
import hmac
import json
import random
import secrets
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.webhooks.models import WebhookEndpoint, WebhookDelivery

DELIVERY_TIMEOUT_SECONDS = 5.0
BACKOFF_BASE_SECONDS = 30  # 30s, 60s, 2m, 4m, 8m, 16m ...


def generate_secret() -> str:
    return "whsec_" + secrets.token_hex(24)


def sign_payload(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 signature, hex-encoded -- the receiver recomputes
    this over the raw request body with the shared secret to verify
    the request genuinely came from CleanFlow and wasn't tampered with
    in transit or forged by a third party."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    expected = sign_payload(secret, raw_body)
    return hmac.compare_digest(expected, signature)


def next_backoff(attempts: int) -> datetime:
    """Exponential backoff with +/-20% jitter, to avoid every failed
    delivery across all endpoints retrying in lockstep (the "thundering
    herd" problem)."""
    base = BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
    jitter = base * random.uniform(-0.2, 0.2)
    return datetime.utcnow() + timedelta(seconds=base + jitter)


def enqueue_deliveries_for_event(db: Session, event_type: str, payload: dict, outbox_event_id: str | None) -> list[WebhookDelivery]:
    endpoints = db.query(WebhookEndpoint).filter(WebhookEndpoint.is_active.is_(True)).all()
    created = []
    for endpoint in endpoints:
        if event_type not in (endpoint.subscribed_events or []):
            continue
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id, outbox_event_id=outbox_event_id, event_type=event_type,
            payload=payload, status="PENDING", next_attempt_at=datetime.utcnow(),
        )
        db.add(delivery)
        created.append(delivery)
    return created


def attempt_delivery(db: Session, delivery: WebhookDelivery) -> None:
    """Perform one HTTP delivery attempt and update the delivery's
    state accordingly. Never raises -- failures are recorded, not
    propagated, since this runs in a background worker loop that must
    keep going regardless of any single delivery's outcome."""
    endpoint = delivery.endpoint
    body = {
        "id": delivery.id,
        "type": delivery.event_type,
        "created_at": delivery.created_at.isoformat(),
        "data": delivery.payload,
    }
    raw_body = json.dumps(body, sort_keys=True, default=str).encode()
    signature = sign_payload(endpoint.secret, raw_body)

    delivery.attempts += 1
    try:
        resp = httpx.post(
            endpoint.url,
            content=raw_body,
            headers={"Content-Type": "application/json", "X-CleanFlow-Signature": signature,
                     "X-CleanFlow-Event": delivery.event_type},
            timeout=DELIVERY_TIMEOUT_SECONDS,
        )
        delivery.last_response_code = resp.status_code
        if 200 <= resp.status_code < 300:
            delivery.status = "SENT"
            delivery.delivered_at = datetime.utcnow()
            delivery.next_attempt_at = None
            return
        delivery.last_error = f"HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        delivery.last_error = str(exc)[:500]

    if delivery.attempts >= delivery.max_attempts:
        delivery.status = "DEAD_LETTER"
        delivery.next_attempt_at = None
    else:
        delivery.status = "FAILED"
        delivery.next_attempt_at = next_backoff(delivery.attempts)


def redeliver(db: Session, delivery: WebhookDelivery) -> None:
    """Manual retry trigger (e.g. from the Settings > Webhooks UI) for
    a dead-lettered delivery, resetting its attempt counter."""
    delivery.status = "PENDING"
    delivery.attempts = 0
    delivery.next_attempt_at = datetime.utcnow()
    delivery.last_error = None
