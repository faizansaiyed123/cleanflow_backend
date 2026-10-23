from fastapi import Request

from app.common.exceptions import AppError
from app.observability.rate_limit import TokenBucketLimiter
from app.observability.metrics import RATE_LIMIT_REJECTIONS
from starlette import status


def rate_limited(limiter: TokenBucketLimiter, bucket_name: str, key_fn=None):
    """FastAPI dependency factory. Keys by client IP by default; a
    login endpoint might additionally key by the submitted email so a
    single attacker IP can't lock out someone else's account by
    exhausting a shared bucket, while still being capped per-IP too."""

    def dependency(request: Request):
        key = key_fn(request) if key_fn else (request.client.host if request.client else "unknown")
        allowed, retry_after = limiter.allow(key)
        if not allowed:
            RATE_LIMIT_REJECTIONS.labels(bucket=bucket_name).inc()
            raise AppError(
                f"Too many requests. Try again in {retry_after:.0f} seconds.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )

    return dependency
