"""
Idempotency-key handling as a reusable FastAPI dependency.

Usage in a route: declare `idem: IdempotencyContext = Depends(idempotency_context("quotes.accept"))`
at the top of the handler, check `if idem.cached_response: return idem.cached_response`
immediately, do the real work, then call `idem.store(status_code, body)`
right before returning. The dependency itself can't short-circuit the
route (FastAPI dependencies can't skip the handler), so the check/store
calls live in the handler -- but the hashing, lookup, and expiry logic
is centralized here so every endpoint that adopts it behaves identically.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Header, Request, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.idempotency.models import IdempotencyKey
from app.common.exceptions import ConflictError

DEFAULT_TTL_HOURS = 24


def _fingerprint(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass
class IdempotencyContext:
    db: Session
    key: str | None
    endpoint: str
    fingerprint: str
    cached_response: dict | None

    def store(self, status_code: int, body: dict) -> None:
        if not self.key:
            return
        record = IdempotencyKey(
            key=self.key, endpoint=self.endpoint, request_fingerprint=self.fingerprint,
            response_status_code=status_code, response_body=body,
            expires_at=datetime.utcnow() + timedelta(hours=DEFAULT_TTL_HOURS),
        )
        self.db.add(record)
        self.db.flush()


def idempotency_context(endpoint: str):
    async def dependency(
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        db: Session = Depends(get_db),
    ) -> IdempotencyContext:
        body = await request.body()
        fingerprint = _fingerprint(body)

        if not idempotency_key:
            return IdempotencyContext(db=db, key=None, endpoint=endpoint, fingerprint=fingerprint, cached_response=None)

        existing = db.query(IdempotencyKey).filter(
            IdempotencyKey.key == idempotency_key, IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.expires_at > datetime.utcnow(),
        ).first()

        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError(
                    "This Idempotency-Key was already used with a different request body. "
                    "Use a new key for a genuinely different request."
                )
            from app.observability.metrics import IDEMPOTENT_REPLAYS
            IDEMPOTENT_REPLAYS.inc()
            return IdempotencyContext(db=db, key=idempotency_key, endpoint=endpoint, fingerprint=fingerprint,
                                       cached_response=existing.response_body)

        return IdempotencyContext(db=db, key=idempotency_key, endpoint=endpoint, fingerprint=fingerprint,
                                   cached_response=None)

    return dependency
