"""
Chat session persistence helpers.

Provides save/load functions used by run_agent_stream to persist conversations
to the database and support context summarization for long sessions.

Message format uses Anthropic's content-block structure:
  - User turns: {"role": "user", "content": str | list[tool_result_block]}
  - Assistant turns: {"role": "assistant", "content": str | list[content_block]}
  - Tool results are batched into a single user turn per assistant turn.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..orm_models import ChatMessageORM, ChatSessionORM

SUMMARY_THRESHOLD = 20   # messages before context summary activates
SUMMARY_TAIL = 10        # recent messages kept verbatim after summarization


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def create_session(db: Session, user_id: Optional[int]) -> ChatSessionORM:
    """Insert a new empty session and return it."""
    now = _now_iso()
    session = ChatSessionORM(
        user_id=user_id,
        title=None,
        created_at=now,
        updated_at=now,
        message_count=0,
        context_summary=None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: int, user_id: Optional[int]) -> Optional[ChatSessionORM]:
    """Load a session, validating ownership. Returns None if not found or not owned."""
    session = db.query(ChatSessionORM).filter(ChatSessionORM.id == session_id).first()
    if session is None:
        return None
    if user_id is not None and session.user_id is not None and session.user_id != user_id:
        return None
    return session


def auto_title_session(db: Session, session: ChatSessionORM, first_user_message: str) -> None:
    """Set title from first 60 chars of first user message if title is not yet set."""
    if session.title is None:
        session.title = first_user_message[:60].strip()
        db.commit()


# ---------------------------------------------------------------------------
# Message persistence
# ---------------------------------------------------------------------------

def save_message(
    db: Session,
    session: ChatSessionORM,
    role: str,
    content: Optional[str],
    metadata: Optional[dict | list] = None,
) -> ChatMessageORM:
    """Insert a message row and bump the session's message_count and updated_at."""
    msg = ChatMessageORM(
        session_id=session.id,
        role=role,
        content=content,
        meta=json.dumps(metadata) if metadata is not None else None,
        created_at=_now_iso(),
    )
    db.add(msg)
    session.message_count += 1
    session.updated_at = _now_iso()
    db.commit()
    db.refresh(msg)
    return msg


# ---------------------------------------------------------------------------
# History reconstruction
# ---------------------------------------------------------------------------

def load_session_messages(db: Session, session: ChatSessionORM) -> list[dict]:
    """
    Reconstruct a list of Anthropic message dicts from stored ChatMessageORM rows.

    DB row roles:
      "user"      → plain user text (content = str)
      "assistant" → may have meta = [{id, name, input}, ...] for tool use blocks
      "tool"      → tool result; meta = {tool_use_id, name}
                    Consecutive tool rows are batched into one user turn.

    If the session has a context_summary and is long, returns only the most
    recent SUMMARY_TAIL messages (the summary is injected via the system prompt).
    """
    rows = (
        db.query(ChatMessageORM)
        .filter(ChatMessageORM.session_id == session.id)
        .order_by(ChatMessageORM.id)
        .all()
    )

    # If summary is active, only use the tail
    if session.context_summary and session.message_count > SUMMARY_THRESHOLD:
        rows = rows[-SUMMARY_TAIL:]

    messages: list[dict] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        meta = json.loads(row.meta) if row.meta else None

        if row.role == "user":
            messages.append({"role": "user", "content": row.content or ""})
            i += 1

        elif row.role == "assistant":
            if meta and isinstance(meta, list):
                # Assistant turn that included tool use — rebuild content blocks
                content_blocks: list[dict] = []
                if row.content:
                    content_blocks.append({"type": "text", "text": row.content})
                for tu in meta:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu.get("input", {}),
                    })
                messages.append({"role": "assistant", "content": content_blocks})
            else:
                messages.append({"role": "assistant", "content": row.content or ""})
            i += 1

        elif row.role == "tool":
            # Batch consecutive tool rows into a single user turn with tool_result blocks
            tool_result_blocks: list[dict] = []
            while i < len(rows) and rows[i].role == "tool":
                r = rows[i]
                m = json.loads(r.meta) if r.meta else {}
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_use_id", ""),
                    "content": r.content or "",
                })
                i += 1
            messages.append({"role": "user", "content": tool_result_blocks})

        else:
            i += 1

    return messages


# ---------------------------------------------------------------------------
# Context summarization (short-term memory)
# ---------------------------------------------------------------------------

async def maybe_summarize(
    db: Session,
    session: ChatSessionORM,
    client,  # AsyncAnthropic instance
    model: str,
) -> None:
    """
    If the session has grown past SUMMARY_THRESHOLD and the count is a multiple
    of 10, generate a fresh context summary from messages excluding the tail.
    """
    if session.message_count <= SUMMARY_THRESHOLD:
        return
    if session.message_count % 10 != 0:
        return

    rows = (
        db.query(ChatMessageORM)
        .filter(ChatMessageORM.session_id == session.id)
        .order_by(ChatMessageORM.id)
        .all()
    )
    rows_to_summarize = rows[:-SUMMARY_TAIL]
    if not rows_to_summarize:
        return

    convo_text = []
    for row in rows_to_summarize:
        if row.role in ("user", "assistant") and row.content:
            convo_text.append(f"{row.role.upper()}: {row.content}")

    if not convo_text:
        return

    summary_prompt = (
        "Summarize the key scheduling decisions and context from this conversation excerpt. "
        "Focus on: what was changed, who was assigned where, any constraints or preferences mentioned. "
        "Be concise (max 200 words).\n\n"
        + "\n".join(convo_text)
    )

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = resp.content[0].text if resp.content else ""
        session.context_summary = summary
        db.commit()
    except Exception:
        pass  # summarization failure is non-fatal
