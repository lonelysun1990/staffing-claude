"""Artifact store: compact JSON blobs keyed by id (DB-backed, TTL)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..orm_models import ArtifactORM

MAX_ARTIFACT_BYTES = 512 * 1024
DEFAULT_TTL_MINUTES = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def purge_expired_artifacts(db: Session) -> int:
    """Delete expired rows. Returns count removed."""
    now = _now_iso()
    q = db.query(ArtifactORM).filter(ArtifactORM.expires_at < now)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n


def store_artifact(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int],
    payload: Any,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> tuple[str, str]:
    """
    Serialize payload to JSON and persist. Returns (artifact_id, status_message).
    """
    purge_expired_artifacts(db)
    raw = json.dumps(payload, default=str).encode("utf-8")
    if len(raw) > MAX_ARTIFACT_BYTES:
        return (
            "",
            f"ERROR: Payload exceeds max size ({MAX_ARTIFACT_BYTES} bytes). "
            "Use aggregate tools and smaller structures.",
        )
    ttl = max(1, min(int(ttl_minutes or DEFAULT_TTL_MINUTES), 24 * 60))
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl)
    row = ArtifactORM(
        id=aid,
        user_id=user_id,
        session_id=session_id,
        content_type="application/json",
        payload_json=raw.decode("utf-8"),
        byte_size=len(raw),
        created_at=now.isoformat(),
        expires_at=exp.isoformat(),
    )
    db.add(row)
    db.commit()
    return (aid, f"OK: Stored artifact {aid} (expires after {ttl} min, {len(raw)} bytes).")


def load_artifact_json(
    db: Session,
    artifact_id: str,
    user_id: Optional[int],
    session_id: Optional[int],
) -> tuple[Optional[Any], Optional[str]]:
    """
    Load and parse JSON if authorized. Returns (data, error_message).
    """
    purge_expired_artifacts(db)
    row = db.query(ArtifactORM).filter(ArtifactORM.id == artifact_id).first()
    if not row:
        return None, f"ERROR: Artifact '{artifact_id}' not found or expired."
    if row.user_id != user_id:
        return None, "ERROR: Artifact does not belong to this user."
    if row.session_id is not None and row.session_id != session_id:
        return None, "ERROR: Artifact does not belong to this chat session."
    try:
        return json.loads(row.payload_json), None
    except json.JSONDecodeError as e:
        return None, f"ERROR: Corrupt artifact payload: {e}"
