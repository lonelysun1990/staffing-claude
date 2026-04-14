import ast
import json
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..orm_models import DynamicToolORM
from ..database import SessionLocal
from .env_manager import create_tool_environment, delete_tool_environment, environment_exists

# Names that dynamic tools cannot shadow
RESERVED_NAMES = frozenset({
    "set_assignment", "clear_assignment", "get_availability", "check_conflicts",
    "suggest_data_scientists", "update_data_scientist", "update_project",
    "create_data_scientist", "create_project", "remember_fact", "list_memories",
    "create_dynamic_tool", "list_dynamic_tools", "delete_dynamic_tool",
})

MAX_CODE_BYTES = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_tool_code(code: str, function_name: str) -> Optional[str]:
    """Returns error string or None if valid."""
    if len(code.encode()) > MAX_CODE_BYTES:
        return f"Code exceeds {MAX_CODE_BYTES} byte limit"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error: {e}"
    names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if function_name not in names:
        return f"Code must define a function named '{function_name}'"
    return None


def _setup_env_background(tool_id: int, tool_name: str, requirements: list) -> None:
    """Runs in a background thread so pip install never blocks the event loop."""
    with SessionLocal() as db:
        result = create_tool_environment(tool_name, requirements)
        tool = db.query(DynamicToolORM).filter(DynamicToolORM.id == tool_id).first()
        if tool:
            tool.env_status = "ready" if result["ok"] else "failed"
            tool.env_error = result.get("error") if not result["ok"] else None
            db.commit()


def create_dynamic_tool(
    db: Session,
    name: str,
    description: str,
    parameters_schema: dict,
    code: str,
    requirements: list,
    tags: Optional[list] = None,
) -> tuple[DynamicToolORM, str]:
    """
    Inserts the tool row immediately. If requirements exist, kicks off background
    thread for pip install and returns env_status="pending".
    Returns (tool, status_message).
    """
    tool = DynamicToolORM(
        name=name,
        description=description,
        parameters_schema=json.dumps(parameters_schema),
        code=code,
        requirements=json.dumps(requirements),
        env_status="pending" if requirements else "ready",
        created_at=_now(),
        updated_at=_now(),
        tags=json.dumps(tags) if tags else None,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)

    if requirements:
        threading.Thread(
            target=_setup_env_background,
            args=(tool.id, tool.name, requirements),
            daemon=True,
        ).start()
        param_names = list(parameters_schema.get('properties', {}).keys())
        msg = (
            f"Tool '{name}' created. Installing {len(requirements)} package(s) in background: {', '.join(requirements)}. "
            f"NEXT: Call check_dynamic_tool_status('{name}') to wait for installation to complete. "
            f"Once ready, fetch required data and call {name}(). "
            f"Parameters: {param_names or ['none']}"
        )
    else:
        param_names = list(parameters_schema.get('properties', {}).keys())
        msg = (
            f"Tool '{name}' created and ready (no packages to install). "
            f"NEXT: Fetch any required data using existing tools (e.g., get_availability), "
            f"then call {name}() passing that data. "
            f"Parameters: {param_names or ['none']}"
        )

    return tool, msg


def get_dynamic_tool_by_name(db: Session, name: str) -> Optional[DynamicToolORM]:
    return db.query(DynamicToolORM).filter(DynamicToolORM.name == name).first()


def list_dynamic_tools(db: Session) -> list[DynamicToolORM]:
    return db.query(DynamicToolORM).order_by(DynamicToolORM.name).all()


def increment_usage(db: Session, tool_id: int) -> None:
    tool = db.query(DynamicToolORM).filter(DynamicToolORM.id == tool_id).first()
    if tool:
        tool.usage_count += 1
        tool.last_used_at = _now()
        db.commit()


def delete_dynamic_tool(db: Session, name: str) -> bool:
    tool = get_dynamic_tool_by_name(db, name)
    if tool:
        delete_tool_environment(name)
        db.delete(tool)
        db.commit()
        return True
    return False


def ensure_tool_environments() -> None:
    """Called at startup to recreate any venvs missing due to redeploy."""
    with SessionLocal() as db:
        tools = db.query(DynamicToolORM).filter(DynamicToolORM.env_status == "ready").all()
        missing = [
            (t.id, t.name, json.loads(t.requirements))
            for t in tools
            if not environment_exists(t.name)
        ]

    for tool_id, tool_name, reqs in missing:
        print(f"[startup] Recreating missing venv for tool '{tool_name}'...")
        threading.Thread(
            target=_setup_env_background,
            args=(tool_id, tool_name, reqs),
            daemon=True,
        ).start()


def wait_for_tool_ready(
    db: Session,
    tool_name: str,
    max_wait_seconds: int = 60,
    poll_interval: float = 3.0,
) -> tuple[str, Optional[str]]:
    """
    Poll until tool's env_status is no longer 'pending' or timeout.
    Returns (status, error_message).
    status is one of: 'ready', 'failed', 'pending' (if timeout), 'not_found'
    """
    tool = get_dynamic_tool_by_name(db, tool_name)
    if not tool:
        return ("not_found", f"Tool '{tool_name}' does not exist")

    elapsed = 0.0
    while tool.env_status == "pending" and elapsed < max_wait_seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        db.refresh(tool)

    if tool.env_status == "ready":
        return ("ready", None)
    elif tool.env_status == "failed":
        return ("failed", tool.env_error)
    else:
        return ("pending", f"Still installing after {max_wait_seconds}s")


def ensure_tool_environment_ready(
    db: Session,
    tool: DynamicToolORM,
    max_wait_seconds: int = 30,
) -> tuple[bool, str]:
    """
    Ensure a tool's venv exists and is ready. Handles:
    1. env_status='ready' but venv missing -> rebuild and wait
    2. env_status='pending' -> wait for completion
    3. env_status='failed' -> return error

    Returns (is_ready, message).
    """
    requirements = json.loads(tool.requirements) if tool.requirements else []

    # Case 1: Status says ready but venv is missing (e.g., after redeploy)
    if tool.env_status == "ready" and not environment_exists(tool.name):
        tool.env_status = "pending"
        tool.env_error = None
        db.commit()

        # Rebuild in background
        threading.Thread(
            target=_setup_env_background,
            args=(tool.id, tool.name, requirements),
            daemon=True,
        ).start()

    # Case 2: Wait if pending
    if tool.env_status == "pending":
        status, error = wait_for_tool_ready(db, tool.name, max_wait_seconds)
        if status == "ready":
            return (True, "Environment ready")
        elif status == "failed":
            return (False, f"Environment setup failed: {error}")
        else:
            return (False, f"Environment still installing. Try again in a moment.")

    # Case 3: Already ready
    if tool.env_status == "ready":
        return (True, "Environment ready")

    # Case 4: Failed
    return (False, f"Environment setup failed: {tool.env_error}")
