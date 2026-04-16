"""DB-backed dynamic Python tools: venv per tool, sandbox execution."""

from __future__ import annotations

import ast
import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..orm_models import DynamicToolORM
from .artifacts import load_artifact_json
from .env_manager import (
    create_tool_environment,
    delete_tool_environment,
    environment_exists,
)
from .sandbox import ENTRYPOINT_FUNC, execute_in_sandbox

MAX_CODE_BYTES = 48_000

RESERVED_NAMES = frozenset({
    "set_assignment",
    "clear_assignment",
    "get_availability",
    "check_conflicts",
    "suggest_data_scientists",
    "update_data_scientist",
    "update_project",
    "create_data_scientist",
    "create_project",
    "remember_fact",
    "list_memories",
    "store_artifact",
    "get_ds_team_weekly_aggregates",
    "create_dynamic_tool",
    "update_dynamic_tool",
    "list_dynamic_tools",
    "delete_dynamic_tool",
    "run_dynamic_tool",
    "check_dynamic_tool_status",
})

TOOL_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_tool_name(name: str) -> Optional[str]:
    if not TOOL_NAME_RE.match(name or ""):
        return (
            "Invalid tool name: use 1–64 chars, start with a letter, "
            "only letters, digits, underscore, hyphen."
        )
    if name in RESERVED_NAMES:
        return f"'{name}' is reserved"
    return None


def validate_tool_code(code: str) -> Optional[str]:
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return f"Code exceeds {MAX_CODE_BYTES} bytes"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error: {e}"
    names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if ENTRYPOINT_FUNC not in names:
        return f"Code must define a function named '{ENTRYPOINT_FUNC}(**kwargs)'"
    return None


def _setup_env_background(tool_id: int, tool_name: str, requirements: list) -> None:
    with SessionLocal() as db:
        result = create_tool_environment(tool_name, requirements)
        tool = db.query(DynamicToolORM).filter(DynamicToolORM.id == tool_id).first()
        if tool:
            tool.env_status = "ready" if result["ok"] else "failed"
            tool.env_error = result.get("error") if not result["ok"] else None
            tool.updated_at = _now()
            db.commit()


def create_dynamic_tool(
    db: Session,
    name: str,
    description: str,
    parameters_schema: dict,
    code: str,
    requirements: list,
    tags: Optional[list] = None,
) -> tuple[Optional[DynamicToolORM], str]:
    err = validate_tool_name(name)
    if err:
        return None, f"ERROR: {err}"
    if get_dynamic_tool_by_name(db, name):
        return None, f"ERROR: Tool '{name}' already exists. Use update_dynamic_tool to replace it."
    err = validate_tool_code(code)
    if err:
        return None, f"ERROR: {err}"

    reqs = requirements or []
    tool = DynamicToolORM(
        name=name,
        description=description,
        parameters_schema=json.dumps(parameters_schema),
        code=code,
        requirements=json.dumps(reqs),
        env_status="pending" if reqs else "ready",
        env_error=None,
        created_at=_now(),
        updated_at=_now(),
        tags=json.dumps(tags) if tags else None,
        code_revision=1,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)

    if reqs:
        threading.Thread(
            target=_setup_env_background,
            args=(tool.id, tool.name, reqs),
            daemon=True,
        ).start()
        msg = (
            f"Tool '{name}' registered (code_revision={tool.code_revision}). "
            f"Installing packages in background: {', '.join(reqs)}. "
            f"Call check_dynamic_tool_status('{name}'), then run_dynamic_tool to test."
        )
    else:
        msg = (
            f"Tool '{name}' registered and ready (no extra packages). "
            f"Call run_dynamic_tool('{name}', ...) to test immediately."
        )

    return tool, f"OK: {msg}"


def update_dynamic_tool(
    db: Session,
    name: str,
    description: Optional[str] = None,
    parameters_schema: Optional[dict] = None,
    code: Optional[str] = None,
    requirements: Optional[list] = None,
    tags: Optional[list] = None,
) -> tuple[bool, str]:
    tool = get_dynamic_tool_by_name(db, name)
    if not tool:
        return False, f"ERROR: Tool '{name}' not found. Use create_dynamic_tool first."

    reqs_old = json.loads(tool.requirements or "[]")
    if code is not None:
        err = validate_tool_code(code)
        if err:
            return False, f"ERROR: {err}"
        tool.code = code
    if description is not None:
        tool.description = description
    if parameters_schema is not None:
        tool.parameters_schema = json.dumps(parameters_schema)
    if tags is not None:
        tool.tags = json.dumps(tags)

    tool.code_revision = (tool.code_revision or 0) + 1
    tool.updated_at = _now()

    reqs_new = reqs_old if requirements is None else (requirements or [])
    req_changed = json.dumps(sorted(reqs_old)) != json.dumps(sorted(reqs_new))
    if requirements is not None:
        tool.requirements = json.dumps(reqs_new)

    if req_changed:
        tool.env_status = "pending"
        tool.env_error = None
        delete_tool_environment(name)
        db.commit()
        db.refresh(tool)
        if reqs_new:
            threading.Thread(
                target=_setup_env_background,
                args=(tool.id, tool.name, reqs_new),
                daemon=True,
            ).start()
        else:
            tool.env_status = "ready"
            db.commit()
        return True, (
            f"OK: Updated '{name}' (code_revision={tool.code_revision}). "
            f"Environment rebuilding due to requirement change. "
            f"Use check_dynamic_tool_status('{name}') then run_dynamic_tool again."
        )

    db.commit()
    return True, (
        f"OK: Updated '{name}' (code_revision={tool.code_revision}). "
        f"Requirements unchanged — same venv. Run run_dynamic_tool to verify."
    )


def get_dynamic_tool_by_name(db: Session, name: str) -> Optional[DynamicToolORM]:
    return db.query(DynamicToolORM).filter(DynamicToolORM.name == name).first()


def list_dynamic_tools(db: Session) -> list[DynamicToolORM]:
    return db.query(DynamicToolORM).order_by(DynamicToolORM.name).all()


def increment_usage(db: Session, tool_id: int) -> None:
    t = db.query(DynamicToolORM).filter(DynamicToolORM.id == tool_id).first()
    if t:
        t.usage_count = (t.usage_count or 0) + 1
        t.last_used_at = _now()
        db.commit()


def delete_dynamic_tool(db: Session, name: str) -> bool:
    tool = get_dynamic_tool_by_name(db, name)
    if not tool:
        return False
    delete_tool_environment(name)
    db.delete(tool)
    db.commit()
    return True


def wait_for_tool_ready(
    db: Session,
    tool_name: str,
    max_wait_seconds: int = 90,
    poll_interval: float = 2.0,
) -> tuple[str, Optional[str]]:
    tool = get_dynamic_tool_by_name(db, tool_name)
    if not tool:
        return "not_found", f"Tool '{tool_name}' does not exist"
    elapsed = 0.0
    while tool.env_status == "pending" and elapsed < max_wait_seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        db.refresh(tool)
    if tool.env_status == "ready":
        return "ready", None
    if tool.env_status == "failed":
        return "failed", tool.env_error
    return "pending", f"Still installing after {max_wait_seconds}s"


def ensure_tool_environment_ready(
    db: Session,
    tool: DynamicToolORM,
    max_wait_seconds: int = 60,
) -> tuple[bool, str]:
    requirements = json.loads(tool.requirements or "[]")

    if tool.env_status == "ready" and not environment_exists(tool.name):
        tool.env_status = "pending"
        tool.env_error = None
        db.commit()
        threading.Thread(
            target=_setup_env_background,
            args=(tool.id, tool.name, requirements),
            daemon=True,
        ).start()

    if tool.env_status == "pending":
        status, error = wait_for_tool_ready(db, tool.name, max_wait_seconds)
        if status == "ready":
            return True, "Environment ready"
        if status == "failed":
            return False, f"Environment setup failed: {error}"
        return False, "Environment still installing. Try check_dynamic_tool_status and run again shortly."

    if tool.env_status == "ready":
        return True, "Environment ready"

    return False, f"Environment setup failed: {tool.env_error}"


def run_dynamic_tool(
    db: Session,
    tool_name: str,
    arguments: Optional[dict],
    artifact_id: Optional[str],
    user_id: Optional[int],
    session_id: Optional[int],
) -> str:
    tool = get_dynamic_tool_by_name(db, tool_name)
    if not tool:
        return _format_run_result(
            {"ok": False, "error": f"Unknown tool '{tool_name}'"},
        )

    ready, env_msg = ensure_tool_environment_ready(db, tool)
    if not ready:
        return _format_run_result(
            {
                "ok": False,
                "error": env_msg,
                "env_status": tool.env_status,
                "env_error": tool.env_error,
            },
        )

    args: dict[str, Any] = dict(arguments or {})
    if artifact_id:
        data, err = load_artifact_json(db, artifact_id, user_id, session_id)
        if err:
            return _format_run_result({"ok": False, "error": err.replace("ERROR: ", "")})
        if isinstance(data, dict):
            merged = {**data, **args}
        else:
            merged = {"_artifact": data, **args}
        args = merged

    result = execute_in_sandbox(tool.name, tool.code, args)
    if result.get("ok"):
        increment_usage(db, tool.id)
    return _format_run_result(result)


def _format_run_result(payload: dict) -> str:
    """Single-line JSON after OK: / ERROR: for MCP text tools."""
    if payload.get("ok"):
        return "OK: " + json.dumps(payload, default=str)
    err = dict(payload)
    err.setdefault("ok", False)
    return "ERROR: " + json.dumps(err, default=str)


def check_dynamic_tool_status(db: Session, name: str) -> str:
    tool = get_dynamic_tool_by_name(db, name)
    if not tool:
        return f"ERROR: Tool '{name}' not found."
    return "OK: " + json.dumps(
        {
            "name": tool.name,
            "env_status": tool.env_status,
            "env_error": tool.env_error,
            "code_revision": tool.code_revision,
            "requirements": json.loads(tool.requirements or "[]"),
        },
        default=str,
    )


def ensure_tool_environments() -> None:
    """Startup: recreate venvs missing after redeploy."""
    with SessionLocal() as db:
        tools = (
            db.query(DynamicToolORM)
            .filter(DynamicToolORM.env_status == "ready")
            .all()
        )
        missing: list[tuple[int, str, list]] = []
        for t in tools:
            reqs = json.loads(t.requirements or "[]")
            if reqs and not environment_exists(t.name):
                missing.append((t.id, t.name, reqs))

    for tool_id, tool_name, reqs in missing:
        threading.Thread(
            target=_setup_env_background,
            args=(tool_id, tool_name, reqs),
            daemon=True,
        ).start()
