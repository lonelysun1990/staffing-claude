from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import List, Optional

from pydantic import BaseModel

from .models import AssignmentCreate, AssignmentsPayload
from .storage import Store


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AgentRequest(BaseModel):
    messages: List[ChatMessage]


class AgentResponse(BaseModel):
    reply: str
    data_changed: bool


# ---------------------------------------------------------------------------
# OpenAI tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_assignment",
            "description": (
                "Set a data scientist's allocation on a project for a range of weeks. "
                "Existing assignments for that person+project within the date range are replaced. "
                "If week_start is null, applies to ALL upcoming weeks within the planning horizon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_scientist_name": {
                        "type": "string",
                        "description": "Name of the data scientist (partial match accepted)",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project (partial match accepted)",
                    },
                    "allocation": {
                        "type": "number",
                        "description": "Allocation fraction 0.0–1.0 (e.g. 0.25 = 25%)",
                    },
                    "week_start": {
                        "type": ["string", "null"],
                        "description": "ISO date (YYYY-MM-DD) of first week to set, or null for all upcoming weeks",
                    },
                    "week_end": {
                        "type": ["string", "null"],
                        "description": "ISO date (YYYY-MM-DD) of last week to set (inclusive), or null for open-ended",
                    },
                },
                "required": ["data_scientist_name", "project_name", "allocation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_assignment",
            "description": (
                "Remove all assignments for a data scientist on a project, optionally within a date range. "
                "If no dates given, removes all weeks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_scientist_name": {
                        "type": "string",
                        "description": "Name of the data scientist (partial match accepted)",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Name of the project (partial match accepted)",
                    },
                    "week_start": {
                        "type": ["string", "null"],
                        "description": "ISO date of first week to clear, or null for all weeks",
                    },
                    "week_end": {
                        "type": ["string", "null"],
                        "description": "ISO date of last week to clear (inclusive), or null for open-ended",
                    },
                },
                "required": ["data_scientist_name", "project_name"],
            },
        },
    },
]


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
    """Return d if it's a Monday, else the next Monday."""
    days_ahead = (7 - d.weekday()) % 7
    return d + timedelta(days=days_ahead) if days_ahead else d


def _upcoming_mondays(horizon_weeks: int) -> list[str]:
    """Return ISO dates for all Mondays from today through the planning horizon."""
    today = date.today()
    start = _next_monday(today)
    return [
        (start + timedelta(weeks=i)).isoformat()
        for i in range(horizon_weeks)
    ]


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def _build_snapshot(store: Store) -> tuple[str, str, str]:
    ds_list = store.list_data_scientists()
    project_list = store.list_projects()
    assignments = store.list_assignments()

    ds_lines = "\n".join(f"  - {ds.name} (id={ds.id})" for ds in ds_list) or "  (none)"
    proj_lines = "\n".join(f"  - {p.name} (id={p.id})" for p in project_list) or "  (none)"

    # Summarise current allocations per DS
    from collections import defaultdict
    ds_id_map = {ds.id: ds.name for ds in ds_list}
    proj_id_map = {p.id: p.name for p in project_list}
    summary: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for a in assignments:
        ds_name = ds_id_map.get(a.data_scientist_id, str(a.data_scientist_id))
        proj_name = proj_id_map.get(a.project_id, str(a.project_id))
        summary[ds_name][proj_name].append(a.allocation)

    assign_lines = []
    for ds_name, proj_map in sorted(summary.items()):
        parts = []
        for proj_name, allocs in sorted(proj_map.items()):
            avg = sum(allocs) / len(allocs)
            parts.append(f"{proj_name} ({avg:.0%} avg over {len(allocs)} weeks)")
        assign_lines.append(f"  {ds_name}: {', '.join(parts)}")
    assign_summary = "\n".join(assign_lines) or "  (no assignments)"

    return ds_lines, proj_lines, assign_summary


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_set_assignment(
    store: Store,
    ds_name_query: str,
    proj_name_query: str,
    allocation: float,
    week_start_str: Optional[str],
    week_end_str: Optional[str],
) -> str:
    """Execute set_assignment tool. Returns a result string (success or clarification needed)."""
    ds_names = [ds.name for ds in store.list_data_scientists()]
    proj_names = [p.name for p in store.list_projects()]

    ds_matches = resolve_name(ds_name_query, ds_names)
    proj_matches = resolve_name(proj_name_query, proj_names)

    if len(ds_matches) == 0:
        return f"ERROR: No data scientist matching '{ds_name_query}' found. Available: {', '.join(ds_names)}"
    if len(ds_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(ds_matches)}. Please specify which one."
    if len(proj_matches) == 0:
        return f"ERROR: No project matching '{proj_name_query}' found. Available: {', '.join(proj_names)}"
    if len(proj_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(proj_matches)}. Please specify which one."

    ds_name = ds_matches[0]
    proj_name = proj_matches[0]

    config = store.get_config()
    ds_list = store.list_data_scientists()
    proj_list = store.list_projects()
    ds = next(d for d in ds_list if d.name == ds_name)
    proj = next(p for p in proj_list if p.name == proj_name)

    # Determine target weeks
    if week_start_str is None:
        target_weeks = set(_upcoming_mondays(config.horizon_weeks))
    else:
        start = date.fromisoformat(week_start_str)
        end = date.fromisoformat(week_end_str) if week_end_str else None
        if end is None:
            # All weeks from start through horizon
            all_upcoming = _upcoming_mondays(config.horizon_weeks)
            target_weeks = {w for w in all_upcoming if w >= week_start_str}
        else:
            target_weeks = set()
            current = start
            while current <= end:
                target_weeks.add(current.isoformat())
                current += timedelta(weeks=1)

    # Build new assignment list: keep all rows NOT in (ds+proj+target_weeks), add new rows
    existing = store.list_assignments()
    kept = [
        a for a in existing
        if not (a.data_scientist_id == ds.id and a.project_id == proj.id and a.week_start in target_weeks)
    ]
    new_rows = [
        AssignmentCreate(
            data_scientist_id=ds.id,
            project_id=proj.id,
            week_start=w,
            allocation=allocation,
        )
        for w in sorted(target_weeks)
    ]
    merged = kept + new_rows
    payload = AssignmentsPayload(assignments=[
        AssignmentCreate(
            data_scientist_id=a.data_scientist_id,
            project_id=a.project_id,
            week_start=a.week_start,
            allocation=a.allocation,
        )
        for a in merged
    ])
    store.replace_assignments(payload)
    return f"OK: Set {ds_name} at {allocation:.0%} on '{proj_name}' for {len(target_weeks)} week(s)."


def _execute_clear_assignment(
    store: Store,
    ds_name_query: str,
    proj_name_query: str,
    week_start_str: Optional[str],
    week_end_str: Optional[str],
) -> str:
    """Execute clear_assignment tool. Returns a result string."""
    ds_names = [ds.name for ds in store.list_data_scientists()]
    proj_names = [p.name for p in store.list_projects()]

    ds_matches = resolve_name(ds_name_query, ds_names)
    proj_matches = resolve_name(proj_name_query, proj_names)

    if len(ds_matches) == 0:
        return f"ERROR: No data scientist matching '{ds_name_query}' found."
    if len(ds_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{ds_name_query}' matches multiple people: {', '.join(ds_matches)}."
    if len(proj_matches) == 0:
        return f"ERROR: No project matching '{proj_name_query}' found."
    if len(proj_matches) > 1:
        return f"CLARIFICATION_NEEDED: '{proj_name_query}' matches multiple projects: {', '.join(proj_matches)}."

    ds_name = ds_matches[0]
    proj_name = proj_matches[0]
    ds_list = store.list_data_scientists()
    proj_list = store.list_projects()
    ds = next(d for d in ds_list if d.name == ds_name)
    proj = next(p for p in proj_list if p.name == proj_name)

    existing = store.list_assignments()
    if week_start_str is None and week_end_str is None:
        # Remove all for this ds+project
        kept = [a for a in existing if not (a.data_scientist_id == ds.id and a.project_id == proj.id)]
    else:
        ws = week_start_str
        we = week_end_str
        kept = [
            a for a in existing
            if not (
                a.data_scientist_id == ds.id
                and a.project_id == proj.id
                and (ws is None or a.week_start >= ws)
                and (we is None or a.week_start <= we)
            )
        ]

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
    store.replace_assignments(payload)
    return f"OK: Removed {removed} assignment(s) for {ds_name} on '{proj_name}'."


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------

def run_agent(request: AgentRequest, store: Store) -> AgentResponse:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return AgentResponse(
            reply="OpenAI API key is not configured. Please add OPENAI_API_KEY to backend/.env.",
            data_changed=False,
        )

    try:
        from openai import OpenAI
    except ImportError:
        return AgentResponse(
            reply="openai package is not installed. Run: pip install openai",
            data_changed=False,
        )

    client = OpenAI(api_key=api_key)

    ds_lines, proj_lines, assign_summary = _build_snapshot(store)
    config = store.get_config()
    today = date.today().isoformat()

    system_prompt = f"""You are a staffing scheduling assistant for a data science team.
Convert plain-English instructions into assignment changes.

Rules:
- Allocation is a fraction: 25% = 0.25, 50% = 0.5, 100% = 1.0
- If no date range is specified, apply to ALL upcoming weeks (today through planning horizon)
- If a name matches multiple people or projects, do NOT guess — ask for clarification
- After making changes, confirm what you did in plain English
- If the instruction is unclear, ask a focused clarifying question
- Today: {today} | Planning horizon: {config.horizon_weeks} weeks

## Current roster
{ds_lines}

## Current projects
{proj_lines}

## Current assignments (summary)
{assign_summary}
"""

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in request.messages]

    data_changed = False
    clarification_reply: Optional[str] = None

    # First LLM call
    response = client.chat.completions.create(
        model="gpt-4o",
        tools=TOOLS,
        messages=messages,
    )
    msg = response.choices[0].message

    if not msg.tool_calls:
        # No tool calls — plain text response (clarification question or answer)
        return AgentResponse(reply=msg.content or "", data_changed=False)

    # Execute tool calls
    messages.append(msg.model_dump(exclude_none=True))
    tool_results = []

    for tc in msg.tool_calls:
        fn_name = tc.function.name
        args = json.loads(tc.function.arguments)

        if fn_name == "set_assignment":
            result = _execute_set_assignment(
                store,
                args["data_scientist_name"],
                args["project_name"],
                args["allocation"],
                args.get("week_start"),
                args.get("week_end"),
            )
        elif fn_name == "clear_assignment":
            result = _execute_clear_assignment(
                store,
                args["data_scientist_name"],
                args["project_name"],
                args.get("week_start"),
                args.get("week_end"),
            )
        else:
            result = f"ERROR: Unknown tool '{fn_name}'"

        if result.startswith("CLARIFICATION_NEEDED:"):
            clarification_reply = result[len("CLARIFICATION_NEEDED:"):].strip()
        elif result.startswith("OK:"):
            data_changed = True

        tool_results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        })

    # If any tool needed clarification, short-circuit and return the question
    if clarification_reply:
        return AgentResponse(reply=clarification_reply, data_changed=data_changed)

    # Second LLM call to get final natural language reply
    messages += tool_results
    follow_up = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
    )
    reply = follow_up.choices[0].message.content or "Done."
    return AgentResponse(reply=reply, data_changed=data_changed)
