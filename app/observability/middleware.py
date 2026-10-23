"""
Middleware for request correlation and request-level metrics. Applied
once, globally, in main.py -- individual routes never need to think
about it.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.observability.logging_setup import request_id_var, user_id_var
from app.observability.metrics import HTTP_REQUESTS, HTTP_REQUEST_DURATION
from app.auth.security import decode_access_token


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_var.set(request_id)

        user_id = "-"
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_access_token(auth_header.removeprefix("Bearer ").strip())
            if payload:
                user_id = payload.get("sub", "-")
        user_token = user_id_var.set(user_id)

        route_template = request.url.path
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(method=request.method, route=route_template, status="500").inc()
            raise
        finally:
            duration = time.perf_counter() - start
            request_id_var.reset(token)
            user_id_var.reset(user_token)

        HTTP_REQUESTS.labels(method=request.method, route=route_template, status=str(response.status_code)).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, route=route_template).observe(duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration * 1000:.1f}"
        return response
