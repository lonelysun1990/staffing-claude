"""
Tool execution layer.

Each _execute_* function is called by the MCP tool handlers in tools.py.

To add a new tool:
  1. Write _execute_<name>() here.
  2. Add a corresponding @tool handler in tools.py.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .. import storage
from ..models import (
    AssignmentCreate,
    AssignmentsPayload,
    DataScientistCreate,
    ProjectCreate,
    ProjectWeek,
)
from ..orm_models import AgentMemoryORM


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

def resolve_name(query: str, candidates: list[str]) -> list[str]:
    """Case-insensitive substring match. Returns all matching candidate names."""
    q = query.strip().lower()
    return [c for c in candidates if q in c.lower()]


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

def _next_monday(d: date) -> date:
    days_ahead = (7 - d.weekday()) % 7
    return d + timedelta(days=days_ahead) if days_ahead else d


def _upcoming_mondays(horizon_weeks: int) -> list[str]:
    today = date.today()
    start = _next_monday(today)
    return [(start + timedelta(weeks=i)).isoformat() for i in range(horizon_weeks)]


def _week_start_str(w) -> str:
    """Normalize DB / API week values to YYYY-MM-DD (handles datetime and date)."""
    if isinstance(w, datetime):
        return w.date().isoformat()
    if isinstance(w, date):
        return w.isoformat()
    s = str(w).strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else s


def _to_date(w) -> date:
    """Coerce assignment week_start to a date."""
    if isinstance(w, datetime):
        return w.date()
    if isinstance(w, date):
        return w
    return date.fromisoformat(_week_start_str(w))


def _week_bucket_key(w) -> str:
    """Canonical key for allocation (same Monday bucket as Gantt / storage)."""
    return storage.canonical_week_monday(_to_date(w)).isoformat()


# ---------------------------------------------------------------------------
# Execute functions
# ---------------------------------------------------------------------------

def _execute_set_assignment(
    db: Session,
    ds_name_query: str,
    proj_name_query: str,
    allocation: float,
    week_start_str: Optional[str],
    week_end_str: Optional[str],
) -> str:
    ds_names = [ds.name for ds in storage.list_data_scientists(db)]
    proj_names = [p.name for p in storage.list_projects(db)]

    ds_matches = resolve_name(ds_name_query, ds_names)
    proj_matches = resolve_name(proj_name_query, proj_names)

    if len(ds_matches) == 0:
        return f"ERROR: No data scientist matching '{ds_name_query}' found. Available: {', '.join(ds_names)}"
    if len(ds_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(ds_matches)}. Please specify."
    if len(proj_matches) == 0:
        return f"ERROR: No project matching '{proj_name_query}' found. Available: {', '.join(proj_names)}"
    if len(proj_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(proj_matches)}. Please specify."

    ds_name = ds_matches[0]
    proj_name = proj_matches[0]
    config = storage.get_config(db)
    ds = next(d for d in storage.list_data_scientists(db) if d.name == ds_name)
    proj = next(p for p in storage.list_projects(db) if p.name == proj_name)

    if week_start_str is None:
        target_weeks = set(_upcoming_mondays(config.horizon_weeks))
    else:
        start = date.fromisoformat(week_start_str[:10])
        end = date.fromisoformat(week_end_str[:10]) if week_end_str else None
        if end is None:
            anchor = storage.canonical_week_monday(start)
            target_weeks = {
                w for w in _upcoming_mondays(config.horizon_weeks)
                if date.fromisoformat(w) >= anchor
            }
        else:
            target_weeks = set(storage.monday_iso_strings_in_range(start, end))

    existing = storage.list_assignments(db)
    kept = [
        a for a in existing
        if not (
            a.data_scientist_id == ds.id
            and a.project_id == proj.id
            and _week_start_str(a.week_start) in target_weeks
        )
    ]
    new_rows = [
        AssignmentCreate(
            data_scientist_id=ds.id,
            project_id=proj.id,
            week_start=date.fromisoformat(w[:10]),
            allocation=allocation,
        )
        for w in sorted(target_weeks)
    ]
    payload = AssignmentsPayload(assignments=[
        AssignmentCreate(
            data_scientist_id=a.data_scientist_id,
            project_id=a.project_id,
            week_start=a.week_start,
            allocation=a.allocation,
        )
        for a in kept
    ] + new_rows)
    storage.replace_assignments(db, payload)
    return f"OK: Set {ds_name} at {allocation:.0%} on '{proj_name}' for {len(target_weeks)} week(s)."


def _execute_clear_assignment(
    db: Session,
    ds_name_query: str,
    proj_name_query: str,
    week_start_str: Optional[str],
    week_end_str: Optional[str],
) -> str:
    ds_names = [ds.name for ds in storage.list_data_scientists(db)]
    ds_matches = resolve_name(ds_name_query, ds_names)
    if len(ds_matches) == 0:
        return f"ERROR: No data scientist matching '{ds_name_query}' found."
    if len(ds_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(ds_matches)}."

    ds = next(d for d in storage.list_data_scientists(db) if d.name == ds_matches[0])
    clear_all = proj_name_query.strip().upper() == "ALL"

    if not clear_all:
        proj_names = [p.name for p in storage.list_projects(db)]
        proj_matches = resolve_name(proj_name_query, proj_names)
        if len(proj_matches) == 0:
            return f"ERROR: No project matching '{proj_name_query}' found."
        if len(proj_matches) > 1:
            return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(proj_matches)}."
        proj = next(p for p in storage.list_projects(db) if p.name == proj_matches[0])
    else:
        proj = None

    ws, we = week_start_str, week_end_str
    existing = storage.list_assignments(db)
    ws_d = date.fromisoformat(ws[:10]) if ws else None
    we_d = date.fromisoformat(we[:10]) if we else None
    ws_mon = storage.canonical_week_monday(ws_d) if ws_d is not None else None
    we_mon = storage.canonical_week_monday(we_d) if we_d is not None else None

    def _matches(a) -> bool:
        if a.data_scientist_id != ds.id:
            return False
        if not clear_all and a.project_id != proj.id:
            return False
        w_mon = storage.canonical_week_monday(a.week_start)
        if ws_mon is not None and w_mon < ws_mon:
            return False
        if we_mon is not None and w_mon > we_mon:
            return False
        return True

    kept = [a for a in existing if not _matches(a)]
    removed = len(existing) - len(kept)
    payload = AssignmentsPayload(assignments=[
        AssignmentCreate(
            data_scientist_id=a.data_scientist_id,
            project_id=a.project_id,
            week_start=a.week_start,
            allocation=a.allocation,
        )
        for a in kept
    ])
    storage.replace_assignments(db, payload)
    proj_label = "all projects" if clear_all else f"'{proj.name}'"
    return f"OK: Removed {removed} assignment(s) for {ds.name} on {proj_label}."


def _execute_get_availability(
    db: Session,
    ds_name_query: Optional[str],
    week_start_str: Optional[str],
    week_end_str: Optional[str],
) -> str:
    ds_list = storage.list_data_scientists(db)
    assignments = storage.list_assignments(db)

    # Use the same Monday-based week grid as set_assignment (see _upcoming_mondays).
    # If we stepped day-by-day from an arbitrary ISO date (e.g. Wed from the planning
    # horizon), keys would not match rows stored on Mondays — availability looked 100% free.
    if week_start_str is None:
        weeks = _upcoming_mondays(4)
    else:
        rs = _to_date(week_start_str)
        if week_end_str:
            re_end = _to_date(week_end_str)
        else:
            re_end = rs + timedelta(weeks=4)
        weeks = storage.monday_iso_strings_in_range(rs, re_end)

    if ds_name_query:
        matches = resolve_name(ds_name_query, [ds.name for ds in ds_list])
        if len(matches) == 0:
            return f"ERROR: No data scientist matching '{ds_name_query}' found."
        if len(matches) > 1:
            return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(matches)}."
        ds_list = [ds for ds in ds_list if ds.name == matches[0]]

    alloc_map: dict[tuple[int, str], float] = defaultdict(float)
    for a in assignments:
        alloc_map[(a.data_scientist_id, _week_bucket_key(a.week_start))] += a.allocation

    lines = []
    for ds in ds_list:
        week_avail = [
            f"{w}: {max(0.0, 1.0 - alloc_map.get((ds.id, w), 0.0)):.0%} free"
            for w in weeks
        ]
        lines.append(f"  {ds.name}:\n    " + "\n    ".join(week_avail))

    return "OK:\n" + "\n".join(lines) if lines else "OK: No data scientists found."


def _execute_check_conflicts(db: Session) -> str:
    conflicts = storage.get_conflicts(db)
    if not conflicts:
        return "OK: No conflicts. All data scientists are within 100% allocation."
    lines = [
        f"  {c['data_scientist_name']} on {c['week_start']}: "
        f"{c['total_allocation']:.0%} total (over by {c['over_by']:.0%})"
        for c in conflicts
    ]
    return "OK: Conflicts detected:\n" + "\n".join(lines)


def _execute_suggest_data_scientists(db: Session, proj_name_query: str) -> str:
    proj_names = [p.name for p in storage.list_projects(db)]
    matches = resolve_name(proj_name_query, proj_names)
    if len(matches) == 0:
        return f"ERROR: No project matching '{proj_name_query}' found. Available: {', '.join(proj_names)}"
    if len(matches) > 1:
        return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(matches)}."

    proj = next(p for p in storage.list_projects(db) if p.name == matches[0])
    suggestions = storage.get_skill_suggestions(db, proj.id)
    if not suggestions:
        return f"OK: No matching data scientists found for '{proj.name}'."
    lines = [
        f"  {ds.name} (level={ds.level}, skills=[{', '.join(ds.skills)}])"
        for ds in suggestions
    ]
    return f"OK: Suggested data scientists for '{proj.name}':\n" + "\n".join(lines)


def _execute_update_data_scientist(
    db: Session,
    ds_name_query: str,
    new_name: Optional[str],
    level: Optional[str],
    efficiency: Optional[float],
    max_concurrent_projects: Optional[int],
    notes,
    skills: Optional[list],
) -> str:
    ds_names = [ds.name for ds in storage.list_data_scientists(db)]
    matches = resolve_name(ds_name_query, ds_names)
    if len(matches) == 0:
        return f"ERROR: No data scientist matching '{ds_name_query}' found. Available: {', '.join(ds_names)}"
    if len(matches) > 1:
        return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(matches)}."

    ds = next(d for d in storage.list_data_scientists(db) if d.name == matches[0])
    payload = DataScientistCreate(
        name=new_name if new_name is not None else ds.name,
        level=level if level is not None else ds.level,
        efficiency=efficiency if efficiency is not None else ds.efficiency,
        max_concurrent_projects=max_concurrent_projects if max_concurrent_projects is not None else ds.max_concurrent_projects,
        notes=notes if notes is not None else ds.notes,
        skills=skills if skills is not None else ds.skills,
    )
    storage.update_data_scientist(db, ds.id, payload)

    changes = []
    if new_name is not None and new_name != ds.name:
        changes.append(f"name: '{ds.name}' → '{new_name}'")
    if level is not None and level != ds.level:
        changes.append(f"level: '{ds.level}' → '{level}'")
    if efficiency is not None and efficiency != ds.efficiency:
        changes.append(f"efficiency: {ds.efficiency} → {efficiency}")
    if max_concurrent_projects is not None and max_concurrent_projects != ds.max_concurrent_projects:
        changes.append(f"max_concurrent_projects: {ds.max_concurrent_projects} → {max_concurrent_projects}")
    if notes is not None:
        changes.append("notes updated")
    if skills is not None:
        changes.append(f"skills → [{', '.join(skills)}]")

    summary = "; ".join(changes) if changes else "none (values already matched)"
    return f"OK: Updated {ds.name}. Changes: {summary}."


def _execute_update_project(
    db: Session,
    proj_name_query: str,
    new_name: Optional[str],
    start_date_str: Optional[str],
    end_date_str: Optional[str],
    required_skills: Optional[list],
) -> str:
    proj_names = [p.name for p in storage.list_projects(db)]
    matches = resolve_name(proj_name_query, proj_names)
    if len(matches) == 0:
        return f"ERROR: No project matching '{proj_name_query}' found. Available: {', '.join(proj_names)}"
    if len(matches) > 1:
        return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(matches)}."

    proj = next(p for p in storage.list_projects(db) if p.name == matches[0])
    new_start = date.fromisoformat(start_date_str) if start_date_str else proj.start_date
    new_end = date.fromisoformat(end_date_str) if end_date_str else proj.end_date

    payload = ProjectCreate(
        name=new_name if new_name is not None else proj.name,
        start_date=new_start,
        end_date=new_end,
        fte_requirements=proj.fte_requirements,
        required_skills=required_skills if required_skills is not None else proj.required_skills,
    )
    storage.update_project(db, proj.id, payload)

    changes = []
    if new_name is not None and new_name != proj.name:
        changes.append(f"name: '{proj.name}' → '{new_name}'")
    if start_date_str is not None and new_start != proj.start_date:
        changes.append(f"start_date: {proj.start_date} → {new_start}")
    if end_date_str is not None and new_end != proj.end_date:
        changes.append(f"end_date: {proj.end_date} → {new_end}")
    if required_skills is not None:
        changes.append(f"required_skills → [{', '.join(required_skills)}]")

    summary = "; ".join(changes) if changes else "none (values already matched)"
    return f"OK: Updated project '{proj.name}'. Changes: {summary}."


def _execute_create_data_scientist(
    db: Session,
    name: str,
    level: str,
    efficiency: float,
    max_concurrent_projects: int,
    notes: Optional[str],
    skills: Optional[list],
) -> str:
    existing_names = [ds.name for ds in storage.list_data_scientists(db)]
    if resolve_name(name, existing_names):
        matches = resolve_name(name, existing_names)
        return (
            f"CLARIFICATION_NEEDED: A data scientist matching '{name}' already exists: "
            f"{', '.join(matches)}. Did you mean update_data_scientist?"
        )
    payload = DataScientistCreate(
        name=name,
        level=level,
        efficiency=efficiency,
        max_concurrent_projects=max_concurrent_projects,
        notes=notes,
        skills=skills or [],
    )
    ds = storage.create_data_scientist(db, payload)
    return f"OK: Created data scientist '{ds.name}' (id={ds.id}, level={ds.level}, efficiency={ds.efficiency})."


def _execute_create_project(
    db: Session,
    name: str,
    start_date_str: str,
    end_date_str: str,
    required_skills: Optional[list],
) -> str:
    existing_names = [p.name for p in storage.list_projects(db)]
    if resolve_name(name, existing_names):
        matches = resolve_name(name, existing_names)
        return (
            f"CLARIFICATION_NEEDED: A project matching '{name}' already exists: "
            f"{', '.join(matches)}. Did you mean update_project?"
        )
    start = date.fromisoformat(start_date_str)
    end = date.fromisoformat(end_date_str)

    weeks: list[ProjectWeek] = []
    current = start
    while current <= end:
        weeks.append(ProjectWeek(week_start=current, fte=1.0))
        current += timedelta(weeks=1)

    payload = ProjectCreate(
        name=name,
        start_date=start,
        end_date=end,
        fte_requirements=weeks,
        required_skills=required_skills or [],
    )
    proj = storage.create_project(db, payload)
    return f"OK: Created project '{proj.name}' (id={proj.id}, {proj.start_date} to {proj.end_date}, {len(weeks)} weeks)."


def _execute_remember_fact(
    db: Session,
    user_id: Optional[int],
    category: str,
    key: str,
    value: str,
    confidence: int = 3,
) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    existing = (
        db.query(AgentMemoryORM)
        .filter(AgentMemoryORM.user_id == user_id, AgentMemoryORM.key == key)
        .first()
    )
    if existing:
        existing.category = category
        existing.value = value
        existing.confidence = confidence
        existing.updated_at = now
    else:
        db.add(AgentMemoryORM(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            confidence=confidence,
            created_at=now,
            updated_at=now,
        ))
    db.commit()
    return f"OK: Remembered [{category}] '{key}': {value}"


def _execute_list_memories(
    db: Session,
    user_id: Optional[int],
    category: Optional[str] = None,
) -> str:
    q = db.query(AgentMemoryORM).filter(AgentMemoryORM.user_id == user_id)
    if category:
        q = q.filter(AgentMemoryORM.category == category)
    memories = q.order_by(AgentMemoryORM.category, AgentMemoryORM.key).all()
    if not memories:
        return "OK: No memories stored yet."
    lines = [
        f"[{m.category}] {m.key}: {m.value} (confidence={m.confidence})"
        for m in memories
    ]
    return "OK:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifacts & dynamic Python tools (server-side venv; see .claude/plans)
# ---------------------------------------------------------------------------

def _execute_store_artifact(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int],
    payload: dict,
    ttl_minutes: Optional[int],
) -> str:
    from .artifacts import store_artifact

    _, msg = store_artifact(
        db, user_id, session_id, payload, ttl_minutes or 60,
    )
    return msg


def _execute_get_ds_team_weekly_aggregates(db: Session) -> str:
    """
    Compact series for plotting: mean allocation % across all data scientists per week.
    """
    config = storage.get_config(db)
    weeks = _upcoming_mondays(config.horizon_weeks)
    ds_list = storage.list_data_scientists(db)
    assignments = storage.list_assignments(db)
    alloc_map: dict[tuple[int, str], float] = defaultdict(float)
    for a in assignments:
        alloc_map[(a.data_scientist_id, _week_bucket_key(a.week_start))] += a.allocation
    n = len(ds_list)
    if n == 0:
        return "OK: " + json.dumps(
            {"weeks": weeks, "team_avg_allocation_pct": [], "n_data_scientists": 0},
        )
    team_pcts: list[float] = []
    for w in weeks:
        total = sum(alloc_map.get((ds.id, w), 0.0) for ds in ds_list)
        team_pcts.append(round(100.0 * total / n, 4))
    return "OK: " + json.dumps(
        {
            "weeks": weeks,
            "team_avg_allocation_pct": team_pcts,
            "n_data_scientists": n,
        },
    )


def _execute_create_dynamic_tool(
    db: Session,
    name: str,
    description: str,
    parameters_schema: dict,
    code: str,
    requirements: Optional[list],
    tags: Optional[list],
) -> str:
    from .dynamic_tools import create_dynamic_tool

    _tool, msg = create_dynamic_tool(
        db,
        name=name,
        description=description,
        parameters_schema=parameters_schema,
        code=code,
        requirements=requirements or [],
        tags=tags,
    )
    return msg


def _execute_update_dynamic_tool(
    db: Session,
    name: str,
    description: Optional[str],
    parameters_schema: Optional[dict],
    code: Optional[str],
    requirements: Optional[list],
    tags: Optional[list],
) -> str:
    from .dynamic_tools import update_dynamic_tool

    _ok, msg = update_dynamic_tool(
        db,
        name,
        description=description,
        parameters_schema=parameters_schema,
        code=code,
        requirements=requirements,
        tags=tags,
    )
    return msg


def _execute_list_dynamic_tools(db: Session) -> str:
    from .dynamic_tools import list_dynamic_tools

    tools = list_dynamic_tools(db)
    if not tools:
        return "OK: No dynamic tools registered."
    rows = [
        {
            "name": t.name,
            "env_status": t.env_status,
            "code_revision": t.code_revision,
            "description": (t.description or "")[:120],
        }
        for t in tools
    ]
    return "OK: " + json.dumps(rows, indent=2)


def _execute_delete_dynamic_tool(db: Session, name: str) -> str:
    from .dynamic_tools import delete_dynamic_tool

    if delete_dynamic_tool(db, name):
        return f"OK: Deleted dynamic tool '{name}'."
    return f"ERROR: Tool '{name}' not found."


def _execute_run_dynamic_tool(
    db: Session,
    name: str,
    arguments: Optional[dict],
    artifact_id: Optional[str],
    user_id: Optional[int],
    session_id: Optional[int],
) -> str:
    from .dynamic_tools import run_dynamic_tool

    return run_dynamic_tool(db, name, arguments, artifact_id, user_id, session_id)


def _execute_check_dynamic_tool_status(
    db: Session,
    name: str,
    max_wait_seconds: int = 0,
    poll_interval_seconds: float = 10.0,
) -> str:
    from .dynamic_tools import check_dynamic_tool_status

    return check_dynamic_tool_status(
        db,
        name,
        max_wait_seconds=max_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def _execute_list_skills() -> str:
    from .skill_loader import format_list_skills_ok

    return format_list_skills_ok()


def _execute_get_skill(skill_id: str) -> str:
    from .skill_loader import format_error, format_get_skill_ok, get_skill_body

    ok, msg = get_skill_body(skill_id.strip())
    if not ok:
        return format_error(msg)
    return format_get_skill_ok(msg)

