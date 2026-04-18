"""
Langfuse tracing for the staffing agent (Claude Agent SDK loop).

Follows Langfuse instrumentation practices: trace input = user message, user_id/session_id
on the trace, nested observations per tool call, trace output = assistant text, flush on end.

Credentials (see https://langfuse.com/docs/observability/sdk/python/sdk-v3):
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL (or LANGFUSE_HOST alias)

Import after env is loaded; failures are swallowed so the agent still runs without Langfuse.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Max chars stored per field (avoid huge payloads in Langfuse)
_MAX_USER_MSG = 12_000
_MAX_TOOL_IO = 16_000
_MAX_OUT = 24_000


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _sanitize_tool_input(args: Any) -> Any:
    if args is None:
        return None
    if isinstance(args, dict):
        return {k: _truncate(str(v), 2000) for k, v in list(args.items())[:80]}
    return _truncate(str(args), _MAX_TOOL_IO)


def _apply_trace_user_session_tags(
    lf: Any,
    root: Any,
    *,
    user_id: Optional[str],
    session_id: Optional[str],
    tags: Optional[list[str]],
) -> None:
    """Set Langfuse trace user/session/tags; works across SDK variants."""
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "tags": tags,
    }
    update_trace = getattr(root, "update_trace", None)
    if callable(update_trace):
        update_trace(**kwargs)
        return
    # Some deployments return observations without update_trace; mirror client behavior.
    update_current = getattr(lf, "update_current_trace", None)
    otel_span = getattr(root, "_otel_span", None)
    if callable(update_current) and otel_span is not None:
        from opentelemetry import trace as otel_trace_api

        with otel_trace_api.use_span(otel_span):
            update_current(**kwargs)
        return
    extra_meta: dict[str, Any] = {}
    if user_id is not None:
        extra_meta["user_id"] = user_id
    if session_id is not None:
        extra_meta["session_id"] = session_id
    if tags:
        extra_meta["tags"] = tags
    if extra_meta and callable(getattr(root, "update", None)):
        root.update(metadata=extra_meta)


def langfuse_configured() -> bool:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    return bool(pk and sk)


def _base_url() -> str:
    return (
        os.environ.get("LANGFUSE_BASE_URL", "").strip()
        or os.environ.get("LANGFUSE_HOST", "").strip()
        or "https://cloud.langfuse.com"
    )


def ensure_langfuse_env() -> None:
    """
    Normalize host for the Langfuse SDK (expects LANGFUSE_BASE_URL).
    Strips trailing slashes; maps LANGFUSE_HOST when BASE_URL is unset.
    """
    if not langfuse_configured():
        return
    base = os.environ.get("LANGFUSE_BASE_URL", "").strip()
    host = os.environ.get("LANGFUSE_HOST", "").strip()
    if not base and host:
        os.environ["LANGFUSE_BASE_URL"] = host.rstrip("/")
    elif base:
        os.environ["LANGFUSE_BASE_URL"] = base.rstrip("/")


def log_langfuse_startup() -> None:
    """Log whether Langfuse can authenticate (check Railway logs if traces are missing)."""
    if not langfuse_configured():
        return
    ensure_langfuse_env()
    try:
        from langfuse import get_client
    except ImportError:
        logger.warning("Langfuse env is set but `langfuse` is not installed.")
        return
    try:
        client = get_client()
        ok = client.auth_check()
        if ok:
            logger.info(
                "Langfuse: credentials OK (base_url=%s). Traces should export after each agent turn.",
                os.environ.get("LANGFUSE_BASE_URL", "(default)"),
            )
        else:
            logger.warning(
                "Langfuse: auth_check() failed — traces will not appear. "
                "Verify LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL "
                "(EU: https://cloud.langfuse.com, US: https://us.cloud.langfuse.com).",
            )
    except Exception as exc:
        logger.warning("Langfuse startup check failed: %s", exc)


class StaffingAgentLangfuseRun:
    """One root observation per agent turn + child observations per tool call."""

    __slots__ = ("_lf", "_root", "_tool_obs", "_text_parts", "_ended", "langfuse_trace_id")

    def is_complete(self) -> bool:
        return self._ended

    def __init__(self) -> None:
        self._lf: Any = None
        self._root: Any = None
        self._tool_obs: dict[str, Any] = {}
        self._text_parts: list[str] = []
        self._ended = False
        self.langfuse_trace_id: Optional[str] = None

    @classmethod
    def try_start(
        cls,
        *,
        user_message: str,
        user_id: Optional[int],
        session_id: Optional[int],
        model: str,
        sse_trace_id: str,
    ) -> Optional["StaffingAgentLangfuseRun"]:
        if not langfuse_configured():
            return None
        try:
            from langfuse import get_client
        except ImportError:
            logger.debug("langfuse package not installed; skipping Langfuse tracing.")
            return None

        ensure_langfuse_env()

        run = cls()
        try:
            run._lf = get_client()
            run._root = run._lf.start_observation(
                name="staffing_agent_turn",
                as_type="agent",
                metadata={
                    "feature": "staffing-agent",
                    "sse_trace_id": sse_trace_id,
                    "model": model,
                },
            )
        except Exception as exc:
            logger.warning("Langfuse trace start failed (agent continues): %s", exc)
            return None

        run.langfuse_trace_id = getattr(run._root, "trace_id", None)
        try:
            _apply_trace_user_session_tags(
                run._lf,
                run._root,
                user_id=str(user_id) if user_id is not None else None,
                session_id=str(session_id) if session_id is not None else None,
                tags=["staffing-agent", "claude-agent-sdk"],
            )
        except Exception as exc:
            logger.debug("Langfuse trace user/session/tags skipped: %s", exc)
        try:
            run._root.update(input=_truncate(user_message, _MAX_USER_MSG))
        except Exception as exc:
            logger.warning("Langfuse: could not set turn input (agent continues): %s", exc)
        return run

    def append_text(self, delta: str) -> None:
        if delta:
            self._text_parts.append(delta)

    def on_tool_start(self, tool_use_id: str, name: str, args: Any) -> None:
        if not self._root:
            return
        try:
            obs = self._root.start_observation(
                name=f"tool:{name}",
                as_type="tool",
                input=_sanitize_tool_input(args),
                metadata={"tool_use_id": tool_use_id},
            )
            self._tool_obs[tool_use_id] = obs
        except Exception as exc:
            logger.warning("Langfuse tool span start failed: %s", exc)

    def on_tool_end(self, tool_use_id: str, result_text: str, ok: bool) -> None:
        obs = self._tool_obs.pop(tool_use_id, None)
        if not obs:
            return
        try:
            obs.update(
                output=_truncate(result_text, _MAX_TOOL_IO),
                metadata={"ok": ok},
            )
            obs.end()
        except Exception as exc:
            logger.warning("Langfuse tool span end failed: %s", exc)

    def finish_ok(self, *, data_changed: bool) -> None:
        if self._ended or not self._root or not self._lf:
            return
        try:
            self._ended = True
            out = "".join(self._text_parts)
            self._root.update(
                output=_truncate(out, _MAX_OUT),
                metadata={"data_changed": data_changed},
            )
            self._root.end()
            self._lf.flush()
        except Exception as exc:
            logger.warning("Langfuse finish_ok failed: %s", exc)

    def finish_error(self, message: str) -> None:
        if self._ended or not self._root or not self._lf:
            return
        try:
            self._ended = True
            self._root.update(output={"error": _truncate(message, 4000)})
            self._root.end()
            self._lf.flush()
        except Exception as exc:
            logger.warning("Langfuse finish_error failed: %s", exc)

    def abort_incomplete(self) -> None:
        """End root and any open tool spans if the stream exits without ResultMessage."""
        if self._ended or not self._root or not self._lf:
            return
        try:
            for tid, obs in list(self._tool_obs.items()):
                try:
                    obs.update(output={"error": "incomplete"})
                    obs.end()
                except Exception:
                    pass
            self._tool_obs.clear()
            self._ended = True
            self._root.update(output={"error": "stream_aborted_or_incomplete"})
            self._root.end()
            self._lf.flush()
        except Exception as exc:
            logger.warning("Langfuse abort_incomplete failed: %s", exc)
