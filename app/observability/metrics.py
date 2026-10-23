"""
Prometheus-format metrics, scraped at GET /metrics. Uses prometheus_client
(a pure instrumentation library -- no network calls, no external
service dependency) so any standard Prometheus/Grafana stack can scrape
this endpoint in a real deployment without CleanFlow talking to anyone.
"""
from prometheus_client import Counter, Histogram, Gauge

HTTP_REQUESTS = Counter(
    "cleanflow_http_requests_total", "Total HTTP requests", ["method", "route", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "cleanflow_http_request_duration_seconds", "HTTP request latency", ["method", "route"]
)
OUTBOX_PROCESSED = Counter(
    "cleanflow_outbox_events_processed_total", "Outbox events processed", ["event_type", "outcome"]
)
WEBHOOK_DELIVERIES = Counter(
    "cleanflow_webhook_deliveries_total", "Webhook delivery attempts", ["status"]
)
JOBS_COMPLETED = Counter("cleanflow_jobs_completed_total", "Jobs marked completed")
PAYMENTS_RECORDED = Counter("cleanflow_payments_recorded_total", "Payments recorded")
PAYMENTS_TOTAL_AMOUNT = Counter("cleanflow_payments_amount_total", "Sum of payment amounts recorded")
OUTBOX_QUEUE_DEPTH = Gauge("cleanflow_outbox_queue_depth", "Pending outbox events awaiting processing")
RATE_LIMIT_REJECTIONS = Counter(
    "cleanflow_rate_limit_rejections_total", "Requests rejected by the rate limiter", ["bucket"]
)
IDEMPOTENT_REPLAYS = Counter(
    "cleanflow_idempotent_replays_total", "Requests served from an idempotency-key cache instead of re-executing"
)
OPTIMISTIC_LOCK_CONFLICTS = Counter(
    "cleanflow_optimistic_lock_conflicts_total", "Requests rejected due to a stale version on an update", ["entity"]
)
