"""
Agent loop — powered by the Claude Agent SDK.

The SDK manages the agentic loop internally (model calls, tool dispatch,
iteration). We provide custom tools as an in-process MCP server and stream
the SDK's messages out as SSE events.

SSE event types emitted:
    text_delta      — streamed assistant text token (from StreamEvent)
    tool_call_start — a tool was invoked (from AssistantMessage with ToolUseBlock)
    tool_result     — tool result received (from UserMessage with ToolResultBlock)
    done            — stream finished successfully (includes session_id, data_changed)
    error           — unrecoverable failure
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy.orm import Session

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ProcessError,
)

from .chat_storage import (
    auto_title_session,
    create_session,
    format_history_as_text,
    get_session,
    load_session_messages,
    maybe_summarize,
    save_message,
)
from .context import build_system_prompt
from .models import AgentRequest
from .sse import sse
from .tools import ALL_TOOL_NAMES, build_mcp_server, is_read_only_tool

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 12

logger = logging.getLogger(__name__)


def _ensure_claude_cwd() -> str:
    """Claude Code expects a normal project directory; deploy images often lack .git under /app."""
    default = str(Path(tempfile.gettempdir()) / "staffing-claude-agent")
    root = Path(os.environ.get("AGENT_WORKSPACE_DIR", default))
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        git = shutil.which("git")
        if git:
            subprocess.run(
                [git, "init", "-q"],
                cwd=root,
                check=False,
                capture_output=True,
            )
        else:
            logger.warning(
                "git not found on PATH; Claude Code cwd may need a git repo "
                "(install git in the container or set AGENT_WORKSPACE_DIR)."
            )
    return str(root)


async def run_agent_stream(
    request: AgentRequest,
    db: Session,
    user_id: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream SSE events for a single user message using the Claude Agent SDK.

    The SDK spawns a Claude Code CLI subprocess that handles the full agentic
    loop. Our in-process MCP server (build_mcp_server) routes tool calls to
    the _execute_* functions in executor.py, which have direct DB access via
    closures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield sse("error", {"message": "Anthropic API key is not configured."})
        return

    # ---- Session setup ----
    if request.session_id:
        session = get_session(db, request.session_id, user_id)
        if session is None:
            yield sse("error", {"message": f"Session {request.session_id} not found."})
            return
    else:
        session = create_session(db, user_id)

    new_user_msg = request.messages[-1]

    # Load prior history from DB and format as text for the system prompt
    prior_messages = load_session_messages(db, session)
    prior_history_text = format_history_as_text(prior_messages)

    system_prompt = build_system_prompt(
        db, user_id,
        context_summary=session.context_summary,
        prior_history_text=prior_history_text or None,
    )

    # Persist new user message immediately
    save_message(db, session, "user", new_user_msg.content)
    auto_title_session(db, session, new_user_msg.content)

    # Build in-process MCP server with direct DB access via closures
    mcp_server = build_mcp_server(db, user_id)

    claude_cwd = _ensure_claude_cwd()
    cli_stderr: list[str] = []

    def _on_cli_stderr(line: str) -> None:
        cli_stderr.append(line)
        logger.warning("Claude Code CLI: %s", line)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"staffing": mcp_server},
        max_turns=MAX_TURNS,
        model=MODEL,
        # bypassPermissions maps to --dangerously-skip-permissions; Claude Code
        # refuses that when running as root (typical in Railway). dontAsk only
        # runs tools in allowed_tools — appropriate for this MCP-only agent.
        permission_mode="dontAsk",
        allowed_tools=ALL_TOOL_NAMES,
        include_partial_messages=True,
        cwd=claude_cwd,
        stderr=_on_cli_stderr,
        env={"ANTHROPIC_API_KEY": api_key},
    )

    data_changed = False
    # Map tool_use_id → tool_name so we can label tool_result SSE events
    tool_id_to_name: dict[str, str] = {}

    try:
        async for message in query(prompt=new_user_msg.content, options=options):

            # ---- Streaming text tokens ----
            if isinstance(message, StreamEvent):
                event = message.event
                if (
                    event.get("type") == "content_block_delta"
                    and event.get("delta", {}).get("type") == "text_delta"
                ):
                    delta_text = event["delta"].get("text", "")
                    if delta_text:
                        yield sse("text_delta", {"delta": delta_text})
                continue

            # ---- Skip system/init messages ----
            if isinstance(message, SystemMessage):
                continue

            # ---- Assistant turn: text and/or tool calls ----
            if isinstance(message, AssistantMessage):
                text = ""
                tool_uses: list[ToolUseBlock] = []

                for block in message.content:
                    if isinstance(block, TextBlock):
                        text = block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_uses.append(block)
                        tool_id_to_name[block.id] = block.name
                        yield sse("tool_call_start", {
                            "tool_call_id": block.id,
                            "name": block.name,
                            "args": block.input,
                        })
                        if not is_read_only_tool(block.name):
                            data_changed = True

                # Persist the assistant turn
                if tool_uses:
                    save_message(
                        db, session, "assistant", text or None,
                        metadata=[
                            {"id": tu.id, "name": tu.name, "input": tu.input}
                            for tu in tool_uses
                        ],
                    )
                elif text:
                    save_message(db, session, "assistant", text)
                continue

            # ---- User turn carrying tool results (SDK feeds these back to Claude) ----
            if isinstance(message, UserMessage):
                content = message.content
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        result_text = block.content
                        if isinstance(result_text, list):
                            result_text = " ".join(
                                b.get("text", "") for b in result_text
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        result_text = str(result_text) if result_text is not None else ""
                        tool_name = tool_id_to_name.get(block.tool_use_id, "unknown")
                        if not is_read_only_tool(tool_name):
                            data_changed = True
                        yield sse("tool_result", {
                            "tool_call_id": block.tool_use_id,
                            "name": tool_name,
                            "result": result_text,
                            "ok": not block.is_error,
                        })
                        save_message(
                            db, session, "tool", result_text,
                            metadata={"tool_use_id": block.tool_use_id, "name": tool_name},
                        )
                continue

            # ---- Final result ----
            if isinstance(message, ResultMessage):
                if message.is_error:
                    yield sse("error", {"message": f"Agent error: {message.result or 'unknown'}"})
                    return
                await maybe_summarize(db, session)
                yield sse("done", {
                    "data_changed": data_changed,
                    "session_id": session.id,
                })
                return

    except ProcessError as exc:
        stderr_blob = "\n".join(cli_stderr[-40:]) if cli_stderr else (exc.stderr or "")
        msg = f"Agent error: {exc}"
        if stderr_blob.strip():
            msg = f"{msg}\n--- Claude Code stderr ---\n{stderr_blob.strip()}"
        yield sse("error", {"message": msg, "traceback": traceback.format_exc()})
    except Exception as exc:
        stderr_blob = "\n".join(cli_stderr[-40:]) if cli_stderr else ""
        msg = f"Agent error: {exc}"
        if stderr_blob.strip():
            msg = f"{msg}\n--- Claude Code stderr ---\n{stderr_blob.strip()}"
        yield sse("error", {"message": msg, "traceback": traceback.format_exc()})
