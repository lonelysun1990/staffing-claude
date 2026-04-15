"""
Agent loop — async streaming implementation using the Anthropic API.
"""

from __future__ import annotations

import json
import os
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from .chat_storage import (
    auto_title_session,
    create_session,
    get_session,
    load_session_messages,
    maybe_summarize,
    save_message,
)
from .context import build_system_prompt
from .executor import _dispatch_tool
from .models import AgentRequest
from .sse import sse
from .tools import READ_ONLY_TOOLS, TOOLS

MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 12


async def run_agent_stream(
    request: AgentRequest,
    db: Session,
    user_id: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """
    Agentic loop with SSE streaming and session persistence.

    Uses the Anthropic Messages API with tool use. The loop continues calling
    the model until it produces a text-only reply (stop_reason="end_turn"),
    or until MAX_ITERATIONS is reached.

    Event types emitted:
        text_delta      — streamed assistant text token
        tool_call_start — a tool is about to execute (full args available)
        tool_result     — tool execution complete
        done            — stream finished successfully (includes session_id)
        error           — unrecoverable failure
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield sse("error", {"message": "Anthropic API key is not configured."})
        return

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        yield sse("error", {"message": "anthropic package is not installed. Run: pip install anthropic"})
        return

    client = AsyncAnthropic(api_key=api_key)

    # ---- Session setup ----
    if request.session_id:
        session = get_session(db, request.session_id, user_id)
        if session is None:
            yield sse("error", {"message": f"Session {request.session_id} not found."})
            return
    else:
        session = create_session(db, user_id)

    new_user_msg = request.messages[-1]
    system_prompt = build_system_prompt(db, user_id, session.context_summary)

    # Load prior messages from DB (Claude format — no system message in the list)
    messages: list[dict] = load_session_messages(db, session)
    messages.append({"role": "user", "content": new_user_msg.content})

    # Persist the new user message immediately
    save_message(db, session, "user", new_user_msg.content)
    auto_title_session(db, session, new_user_msg.content)

    data_changed = False

    try:
        for _iteration in range(MAX_ITERATIONS):
            # ---- Single model call with streaming ----
            assistant_text = ""
            tool_uses: list[dict] = []  # [{id, name, input}]
            pending_tool: dict | None = None
            pending_tool_json = ""
            stop_reason = "end_turn"

            async with client.messages.stream(
                model=MODEL,
                max_tokens=8096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                async for event in stream:
                    etype = event.type

                    if etype == "content_block_start":
                        cb = event.content_block
                        if cb.type == "tool_use":
                            pending_tool = {"id": cb.id, "name": cb.name}
                            pending_tool_json = ""

                    elif etype == "content_block_delta":
                        d = event.delta
                        if d.type == "text_delta":
                            assistant_text += d.text
                            yield sse("text_delta", {"delta": d.text})
                        elif d.type == "input_json_delta" and pending_tool is not None:
                            pending_tool_json += d.partial_json

                    elif etype == "content_block_stop":
                        if pending_tool is not None:
                            try:
                                inp = json.loads(pending_tool_json or "{}")
                            except json.JSONDecodeError:
                                inp = {}
                            tool_uses.append({**pending_tool, "input": inp})
                            pending_tool = None
                            pending_tool_json = ""

                    elif etype == "message_delta":
                        if hasattr(event.delta, "stop_reason") and event.delta.stop_reason:
                            stop_reason = event.delta.stop_reason

            # ---- Turn complete ----

            # Build the assistant content blocks for DB and next-turn messages
            content_blocks: list[dict] = []
            if assistant_text:
                content_blocks.append({"type": "text", "text": assistant_text})
            for tu in tool_uses:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                })

            # Append assistant turn to in-memory message list
            messages.append({"role": "assistant", "content": content_blocks})

            # Persist assistant turn
            if tool_uses:
                # Store tool_use blocks as metadata so history can be reconstructed
                save_message(db, session, "assistant", assistant_text or None,
                             metadata=[{"id": tu["id"], "name": tu["name"], "input": tu["input"]}
                                       for tu in tool_uses])
            else:
                save_message(db, session, "assistant", assistant_text)

            # No tool calls → model is done
            if stop_reason == "end_turn" or not tool_uses:
                await maybe_summarize(db, session, client, MODEL)
                yield sse("done", {
                    "data_changed": data_changed,
                    "session_id": session.id,
                })
                return

            # ---- Execute all tool calls and build the tool_result user turn ----
            tool_result_blocks: list[dict] = []

            for tu in tool_uses:
                yield sse("tool_call_start", {
                    "tool_call_id": tu["id"],
                    "name": tu["name"],
                    "args": tu["input"],
                })

                tool_traceback: str | None = None
                try:
                    result = _dispatch_tool(tu["name"], tu["input"], db, user_id=user_id)
                except Exception as tool_exc:
                    import traceback as _tb
                    tool_traceback = _tb.format_exc()
                    result = f"ERROR: {tool_exc}"

                ok = not result.startswith("ERROR:")
                if result.startswith("OK:") and tu["name"] not in READ_ONLY_TOOLS:
                    data_changed = True

                yield sse("tool_result", {
                    "tool_call_id": tu["id"],
                    "name": tu["name"],
                    "result": result,
                    "ok": ok,
                    **({"traceback": tool_traceback} if tool_traceback else {}),
                })

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result,
                })

                # Persist each tool result individually for DB history
                save_message(db, session, "tool", result,
                             metadata={"tool_use_id": tu["id"], "name": tu["name"]})

            # Append all tool results as a single user turn (Claude's required format)
            messages.append({"role": "user", "content": tool_result_blocks})

        # Exhausted max iterations without a clean exit
        yield sse("error", {"message": f"Agent reached the maximum of {MAX_ITERATIONS} iterations."})

    except Exception as exc:
        import traceback as _tb
        yield sse("error", {"message": f"Agent error: {exc}", "traceback": _tb.format_exc()})
