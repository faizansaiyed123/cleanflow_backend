from fastapi import HTTPException, status


class AppError(HTTPException):
    """Base class for expected, user-facing application errors. Using a
    typed hierarchy (instead of raising bare HTTPException everywhere)
    keeps error semantics consistent and makes them easy to unit test."""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundError(AppError):
    def __init__(self, entity: str, entity_id: str | None = None):
        detail = f"{entity} not found" + (f": {entity_id}" if entity_id else "")
        super().__init__(detail, status.HTTP_404_NOT_FOUND)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "You do not have permission to perform this action"):
        super().__init__(detail, status.HTTP_403_FORBIDDEN)


class ConflictError(AppError):
    """Used for invalid state transitions, duplicate actions, scheduling
    conflicts, and other 'this can't happen right now' situations."""

    def __init__(self, detail: str):
        super().__init__(detail, status.HTTP_409_CONFLICT)


class ValidationAppError(AppError):
    def __init__(self, detail: str):
        super().__init__(detail, status.HTTP_422_UNPROCESSABLE_ENTITY)
