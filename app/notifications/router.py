from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import timedelta

from app.config.database import get_db
from app.auth.deps import get_current_user
from app.users.models import User
from app.common.mixins import utcnow
from app.common.exceptions import NotFoundError, AppError
from app.notifications.models import Notification
from app.notifications.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(100).all()


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    count = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.is_read.is_(False)).count()
    return {"count": count}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    note = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == current_user.id).first()
    if not note:
        raise NotFoundError("Notification", notification_id)
    note.is_read = True
    note.read_at = utcnow()
    db.commit()
    db.refresh(note)
    return note


@router.get("/stream-ticket")
def get_stream_ticket(current_user: User = Depends(get_current_user)):
    """
    Issues a short-lived (60s), single-purpose token for opening the SSE
    stream below. The browser's EventSource API cannot set an
    Authorization header, so the stream URL necessarily carries its
    token as a query parameter -- and query parameters are exactly the
    kind of thing that ends up in server access logs, browser history,
    and Referer headers. Minting a narrow, short-lived ticket (rather
    than passing the long-lived main JWT in the URL) means that even if
    a ticket leaks somewhere, it's worthless within a minute and can't
    be used for anything but opening this one stream.
    """
    from app.auth.security import create_access_token
    ticket = create_access_token(subject=current_user.id, role=current_user.role.value,
                                  extra_claims={"scope": "notifications:stream"},
                                  expires_delta=timedelta(seconds=60))
    return {"ticket": ticket, "expires_in_seconds": 60}


@router.get("/stream")
async def stream_notifications(token: str):
    """
    Server-Sent Events stream of live notification updates.

    Why SSE over plain polling: the frontend previously polled
    `/notifications/unread-count` every 30s regardless of whether
    anything changed -- fine at one user, wasteful at scale (N users x
    2 requests/minute of mostly-empty responses, forever). SSE keeps a
    single long-lived HTTP connection open and only sends data when
    there's something new, which is both lower latency (near-instant
    instead of up to 30s stale) and lower load.

    Why not a true push architecture (e.g. an in-memory pub/sub queue
    fed directly by the outbox worker): that thread (APScheduler) and
    this one (the asyncio event loop serving requests) don't share
    memory safely without a broker in between (Redis pub/sub, or an
    asyncio.Queue bridged across threads via call_soon_threadsafe).
    This implementation takes the simpler, still-correct middle ground:
    a short server-side poll (1s) inside the streaming response, which
    gets 90% of the latency benefit of true push with none of the
    cross-thread coordination complexity. The upgrade path to real
    push is a documented, isolated change to this one function.

    Deliberately does NOT take `db: Session = Depends(get_db)`: this
    generator runs for as long as the client stays connected -- often
    minutes to hours -- and holding one request-scoped connection open
    that entire time would mean N concurrently-connected browser tabs
    exhausts the DB connection pool just by having the app open. Instead
    each poll tick opens and closes its own short-lived session, exactly
    like the background worker does, so an SSE connection's DB
    footprint is a quick query once a second, not one held-open
    connection for the connection's whole lifetime.

    Auth via query param (not a header) because EventSource, the
    browser API for consuming SSE, cannot set custom headers.
    """
    import asyncio
    import json as json_module
    from app.auth.security import decode_access_token
    from app.notifications.models import Notification
    from app.config.database import SessionLocal

    payload = decode_access_token(token)
    if not payload or payload.get("scope") != "notifications:stream":
        raise AppError("Invalid or expired stream token", status.HTTP_401_UNAUTHORIZED)
    user_id = payload["sub"]

    def _unread_count(db) -> int:
        return db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read.is_(False)).count()

    async def event_generator():
        last_seen_id = None
        db = SessionLocal()
        try:
            count = _unread_count(db)
        finally:
            db.close()
        yield f"event: unread_count\ndata: {json_module.dumps({'count': count})}\n\n"

        while True:
            await asyncio.sleep(1)
            db = SessionLocal()
            try:
                latest = (
                    db.query(Notification)
                    .filter(Notification.user_id == user_id)
                    .order_by(Notification.created_at.desc())
                    .first()
                )
                if latest and latest.id != last_seen_id:
                    last_seen_id = latest.id
                    count = _unread_count(db)
                    yield f"event: notification\ndata: {json_module.dumps({'title': latest.title, 'body': latest.body, 'count': count})}\n\n"
            finally:
                db.close()
            yield ": keep-alive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
def mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    (db.query(Notification)
     .filter(Notification.user_id == current_user.id, Notification.is_read.is_(False))
     .update({"is_read": True, "read_at": utcnow()}))
    db.commit()
    return {"ok": True}
