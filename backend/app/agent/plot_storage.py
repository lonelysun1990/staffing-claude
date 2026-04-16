"""Persist plot bytes from dynamic tools; return small image_id refs for MCP / chat."""

from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..orm_models import PlotImageORM

MAX_PLOT_BYTES = 6 * 1024 * 1024  # 6 MiB
DEFAULT_PLOT_TTL_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def purge_expired_plot_images(db: Session) -> int:
    now = _now_iso()
    q = db.query(PlotImageORM).filter(PlotImageORM.expires_at < now)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n


def store_plot_bytes(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int],
    raw: bytes,
    mime_type: str = "image/png",
    ttl_hours: int = DEFAULT_PLOT_TTL_HOURS,
) -> tuple[Optional[str], Optional[str]]:
    """Returns (image_id, None) or (None, error_message)."""
    if len(raw) > MAX_PLOT_BYTES:
        return None, f"Plot exceeds max size ({MAX_PLOT_BYTES} bytes)."
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=min(ttl_hours, 24 * 7))
    db.add(
        PlotImageORM(
            id=pid,
            user_id=user_id,
            session_id=session_id,
            mime_type=mime_type,
            data=raw,
            byte_size=len(raw),
            created_at=now.isoformat(),
            expires_at=exp.isoformat(),
        )
    )
    db.commit()
    return pid, None


def _decode_base64_payload(s: str) -> Optional[bytes]:
    s = s.strip()
    if s.startswith("data:image/"):
        # data:image/png;base64,XXXX
        m = re.match(r"data:image/[^;]+;base64,(.+)", s, re.DOTALL)
        if not m:
            return None
        s = m.group(1)
    try:
        return base64.b64decode(s, validate=False)
    except Exception:
        return None


def normalize_plot_result_for_tool_response(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int],
    sandbox_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    If sandbox returned ok + huge base64 plot, store bytes and replace result with a tiny ref dict.
    """
    if not sandbox_payload.get("ok"):
        return sandbox_payload

    inner = sandbox_payload.get("result")
    replaced, new_inner, err = _maybe_replace_plot_result(db, user_id, session_id, inner)
    if err:
        return {"ok": False, "error": err}
    if replaced and new_inner is not None:
        out = dict(sandbox_payload)
        out["result"] = new_inner
        return out
    return sandbox_payload


def _maybe_replace_plot_result(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int],
    inner: Any,
) -> tuple[bool, Optional[dict], Optional[str]]:
    """
    Returns (did_replace, new_result_dict_or_none, error).
    """
    raw: Optional[bytes] = None
    mime = "image/png"

    if isinstance(inner, dict):
        t = inner.get("type")
        if t in ("png_base64", "plot_png_base64", "image_png"):
            b64 = inner.get("data")
            if isinstance(b64, str):
                raw = _decode_base64_payload(b64)
        elif t == "plot_image" and inner.get("format") == "png":
            b64 = inner.get("data")
            if isinstance(b64, str):
                raw = _decode_base64_payload(b64)
    elif isinstance(inner, str):
        raw = _decode_base64_payload(inner)
        if raw is None and inner.startswith("data:image/"):
            raw = _decode_base64_payload(inner)

    if raw is None:
        return False, None, None

    pid, err = store_plot_bytes(db, user_id, session_id, raw, mime_type=mime)
    if err or not pid:
        return False, None, err or "Failed to store plot"

    ref = {
        "type": "image",
        "image_id": pid,
        "mime_type": mime,
        "byte_size": len(raw),
    }
    return True, ref, None


def get_plot_image_row(
    db: Session,
    image_id: str,
    user_id: Optional[int],
    session_id: Optional[int],
) -> Optional[PlotImageORM]:
    row = db.query(PlotImageORM).filter(PlotImageORM.id == image_id).first()
    if not row:
        return None
    if row.user_id != user_id:
        return None
    if row.session_id is not None:
        if session_id is None or row.session_id != session_id:
            return None
    return row
