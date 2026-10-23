"""
Optimistic concurrency control.

Why optimistic rather than pessimistic (row locks): the write patterns
here are "a manager looks at a screen, thinks, then clicks a button" --
seconds to minutes between read and write. Holding a database row lock
for that long would serialize every manager's workflow behind whoever
opened a record first, which is far worse in practice than the rare
case of an actual conflict. Optimistic locking pays the cost only when
a real conflict happens, and it happens rarely.

Every entity that adopts this carries a `version` integer column. A
client reads a record, gets back the version it saw, and must echo
that version back on its next mutating request (as `expected_version`).
If another write has happened in between, the version in the database
has moved on and `check_and_bump_version` raises a 409 -- forcing the
client to re-fetch and decide how to proceed, rather than silently
clobbering someone else's change.
"""
from app.common.exceptions import ConflictError


def check_and_bump_version(entity, expected_version: int | None, entity_name: str) -> None:
    """Call this BEFORE mutating `entity`'s fields. If expected_version
    is None, the caller hasn't opted into concurrency checking for this
    request (kept optional so existing integrations/tests don't have to
    adopt it all at once) and this is a no-op version bump only."""
    if expected_version is not None and expected_version != entity.version:
        from app.observability.metrics import OPTIMISTIC_LOCK_CONFLICTS
        OPTIMISTIC_LOCK_CONFLICTS.labels(entity=entity_name).inc()
        raise ConflictError(
            f"This {entity_name} was modified by someone else since you loaded it "
            f"(expected version {expected_version}, current version {entity.version}). "
            "Refresh and try again."
        )
    entity.version += 1
