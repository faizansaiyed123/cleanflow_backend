"""
Structured (JSON) logging with request-correlation IDs.

Why JSON logs: plain-text log lines are fine to read in a terminal but
are painful to query at scale ("show me every 500 for customer X in the
last hour") -- structured logs are what actually gets ingested by
Datadog/CloudWatch/ELK in a real deployment. request_id ties every log
line emitted while handling one HTTP request together, and is also
returned to the client (X-Request-ID header) so a bug report can be
grep'd straight to the exact request that produced it.
"""
import contextvars
import json
import logging
import sys
from datetime import datetime

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Keep uvicorn's own access logs plain-text (they're already structured
    # enough and reformatting them adds noise); everything application-level
    # goes through the JSON formatter above.
    logging.getLogger("uvicorn.access").propagate = True
