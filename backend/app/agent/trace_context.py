"""
Trace identifiers and structured agent spans for logs.

Each span is logged as one JSON line with "agent_trace": true (filter in Railway/log drains).

Optional: install `langfuse` and set LANGFUSE_* env vars; use Langfuse's OpenTelemetry
or SDK docs to forward these logs — we keep the hot path dependency-free.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_trace_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TraceContext:
    trace_id: str
    model: str
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def emit_agent_span(
    ctx: TraceContext,
    span_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Structured log line for observability pipelines."""
    body: dict[str, Any] = {
        "agent_trace": True,
        "trace_id": ctx.trace_id,
        "span_type": span_type,
        "model": ctx.model,
        "user_id": ctx.user_id,
        "session_id": ctx.session_id,
        "started_at": ctx.started_at,
    }
    if payload:
        body["payload"] = payload
    logger.info("%s", json.dumps(body, default=str))


def enrich_sse_payload(trace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Add trace_id to every SSE JSON body (additive, stable for clients)."""
    out = dict(payload)
    out["trace_id"] = trace_id
    return out
