"""
In-process MCP server for the staffing agent.

Each tool wraps an _execute_* function from executor.py via a closure that
captures the SQLAlchemy Session so tool handlers have direct DB access.

Call build_mcp_server(db, user_id) per request to get a McpSdkServerConfig
ready for ClaudeAgentOptions.mcp_servers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from claude_agent_sdk import create_sdk_mcp_server, tool, McpSdkServerConfig

from .executor import (
    _execute_set_assignment,
    _execute_clear_assignment,
    _execute_get_availability,
    _execute_check_conflicts,
    _execute_suggest_data_scientists,
    _execute_update_data_scientist,
    _execute_update_project,
    _execute_create_data_scientist,
    _execute_create_project,
    _execute_remember_fact,
    _execute_list_memories,
)

_MCP_SERVER = "staffing"


def mcp_tool_id(short_name: str) -> str:
    """Wire name for SDK MCP tools (matches Claude Code --allowedTools / ToolUseBlock.name)."""
    return f"mcp__{_MCP_SERVER}__{short_name}"


def is_read_only_tool(name: str) -> bool:
    """True if this tool does not mutate scheduling data (handles short or MCP-qualified names)."""
    if name in READ_ONLY_TOOLS:
        return True
    return mcp_tool_id(name) in READ_ONLY_TOOLS


# Tools that do not modify data — used by loop.py to decide whether to set data_changed=True.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    mcp_tool_id(n)
    for n in (
        "get_availability",
        "check_conflicts",
        "suggest_data_scientists",
        "list_memories",
    )
)

# All tool names — used to populate ClaudeAgentOptions.allowed_tools (required for dontAsk mode).
ALL_TOOL_NAMES: list[str] = [
    mcp_tool_id(n)
    for n in (
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
    )
]

# ---------------------------------------------------------------------------
# Input schemas (JSON Schema format — same as before)
# ---------------------------------------------------------------------------

_SET_ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "data_scientist_name": {"type": "string", "description": "Name (partial match accepted)"},
        "project_name": {"type": "string", "description": "Project name (partial match accepted)"},
        "allocation": {"type": "number", "description": "Fraction 0.0–1.0 (e.g. 0.25 = 25%)"},
        "week_start": {"type": ["string", "null"], "description": "ISO date of first week, or null for all upcoming"},
        "week_end": {"type": ["string", "null"], "description": "ISO date of last week (inclusive), or null"},
    },
    "required": ["data_scientist_name", "project_name", "allocation"],
}

_CLEAR_ASSIGNMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "data_scientist_name": {"type": "string", "description": "Name (partial match accepted)"},
        "project_name": {"type": "string", "description": "Project name or 'ALL'"},
        "week_start": {"type": ["string", "null"], "description": "ISO date of first week to clear, or null"},
        "week_end": {"type": ["string", "null"], "description": "ISO date of last week to clear, or null"},
    },
    "required": ["data_scientist_name", "project_name"],
}

_GET_AVAILABILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "data_scientist_name": {"type": ["string", "null"], "description": "Name (partial match), or null for all"},
        "week_start": {"type": ["string", "null"], "description": "ISO date of first week, or null"},
        "week_end": {"type": ["string", "null"], "description": "ISO date of last week, or null"},
    },
    "required": [],
}

_CHECK_CONFLICTS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

_SUGGEST_DS_SCHEMA = {
    "type": "object",
    "properties": {
        "project_name": {"type": "string", "description": "Project name (partial match accepted)"},
    },
    "required": ["project_name"],
}

_UPDATE_DS_SCHEMA = {
    "type": "object",
    "properties": {
        "data_scientist_name": {"type": "string", "description": "Current name (partial match accepted)"},
        "new_name": {"type": ["string", "null"]},
        "level": {"type": ["string", "null"]},
        "efficiency": {"type": ["number", "null"]},
        "max_concurrent_projects": {"type": ["integer", "null"]},
        "notes": {"type": ["string", "null"]},
        "skills": {"type": ["array", "null"], "items": {"type": "string"}},
    },
    "required": ["data_scientist_name"],
}

_UPDATE_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "project_name": {"type": "string", "description": "Current name (partial match accepted)"},
        "new_name": {"type": ["string", "null"]},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "required_skills": {"type": ["array", "null"], "items": {"type": "string"}},
    },
    "required": ["project_name"],
}

_CREATE_DS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "level": {"type": "string", "description": "e.g. 'Junior DS', 'Senior DS'"},
        "efficiency": {"type": "number", "description": "FTE multiplier, default 1.0"},
        "max_concurrent_projects": {"type": "integer", "description": "Default 2"},
        "notes": {"type": ["string", "null"]},
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "level"],
}

_CREATE_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        "required_skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "start_date", "end_date"],
}

_REMEMBER_FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["preference", "habit", "note"]},
        "key": {"type": "string"},
        "value": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["category", "key", "value"],
}

_LIST_MEMORIES_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": ["string", "null"], "enum": ["preference", "habit", "note", None]},
    },
    "required": [],
}


# ---------------------------------------------------------------------------
# Per-request MCP server factory
# ---------------------------------------------------------------------------

def build_mcp_server(db: Session, user_id: Optional[int]) -> McpSdkServerConfig:
    """
    Create an in-process MCP server per request.

    Each call returns a new server whose tool handlers close over `db` and
    `user_id`, giving them direct access to the database without any
    ContextVar or global state.
    """

    def _ok(result: str) -> dict:
        return {"content": [{"type": "text", "text": result}], "is_error": False}

    def _result(result: str) -> dict:
        is_err = result.startswith("ERROR:")
        return {"content": [{"type": "text", "text": result}], "is_error": is_err}

    @tool(
        name="set_assignment",
        description=(
            "Set a data scientist's allocation on a project for a range of weeks. "
            "Existing assignments for that person+project within the date range are replaced. "
            "If week_start is null, applies to ALL upcoming weeks within the planning horizon."
        ),
        input_schema=_SET_ASSIGNMENT_SCHEMA,
    )
    async def set_assignment(args: dict) -> dict:
        return _result(_execute_set_assignment(
            db, args["data_scientist_name"], args["project_name"],
            args["allocation"], args.get("week_start"), args.get("week_end"),
        ))

    @tool(
        name="clear_assignment",
        description=(
            "Remove assignments for a data scientist on a project, optionally within a date range. "
            "Specify project_name as 'ALL' to remove from all projects."
        ),
        input_schema=_CLEAR_ASSIGNMENT_SCHEMA,
    )
    async def clear_assignment(args: dict) -> dict:
        return _result(_execute_clear_assignment(
            db, args["data_scientist_name"], args["project_name"],
            args.get("week_start"), args.get("week_end"),
        ))

    @tool(
        name="get_availability",
        description=(
            "Get weekly free capacity (unallocated fraction) for one or all data scientists "
            "over a date range. Use to find who is free or check scheduling gaps."
        ),
        input_schema=_GET_AVAILABILITY_SCHEMA,
    )
    async def get_availability(args: dict) -> dict:
        return _result(_execute_get_availability(
            db, args.get("data_scientist_name"),
            args.get("week_start"), args.get("week_end"),
        ))

    @tool(
        name="check_conflicts",
        description=(
            "Check for over-allocation conflicts across the entire schedule. "
            "Returns every data scientist / week pair where total allocation exceeds 100%."
        ),
        input_schema=_CHECK_CONFLICTS_SCHEMA,
    )
    async def check_conflicts(args: dict) -> dict:
        return _result(_execute_check_conflicts(db))

    @tool(
        name="suggest_data_scientists",
        description=(
            "Suggest data scientists best suited for a project based on skill matching. "
            "Returns a ranked list whose skills overlap with the project's required skills."
        ),
        input_schema=_SUGGEST_DS_SCHEMA,
    )
    async def suggest_data_scientists(args: dict) -> dict:
        return _result(_execute_suggest_data_scientists(db, args["project_name"]))

    @tool(
        name="update_data_scientist",
        description=(
            "Update one or more properties of a data scientist: "
            "name, level, efficiency, max_concurrent_projects, notes, or skills. "
            "Only specified fields are changed; omitted fields keep current values."
        ),
        input_schema=_UPDATE_DS_SCHEMA,
    )
    async def update_data_scientist(args: dict) -> dict:
        return _result(_execute_update_data_scientist(
            db, args["data_scientist_name"], args.get("new_name"),
            args.get("level"), args.get("efficiency"),
            args.get("max_concurrent_projects"), args.get("notes"), args.get("skills"),
        ))

    @tool(
        name="update_project",
        description=(
            "Update one or more properties of a project: "
            "name, start_date, end_date, or required_skills. "
            "Only specified fields are changed."
        ),
        input_schema=_UPDATE_PROJECT_SCHEMA,
    )
    async def update_project(args: dict) -> dict:
        return _result(_execute_update_project(
            db, args["project_name"], args.get("new_name"),
            args.get("start_date"), args.get("end_date"), args.get("required_skills"),
        ))

    @tool(
        name="create_data_scientist",
        description=(
            "Create a new data scientist record. "
            "Use only when the person does not yet exist."
        ),
        input_schema=_CREATE_DS_SCHEMA,
    )
    async def create_data_scientist(args: dict) -> dict:
        return _result(_execute_create_data_scientist(
            db, args["name"], args["level"],
            args.get("efficiency", 1.0), args.get("max_concurrent_projects", 2),
            args.get("notes"), args.get("skills"),
        ))

    @tool(
        name="create_project",
        description=(
            "Create a new project. "
            "Use only when it does not yet exist."
        ),
        input_schema=_CREATE_PROJECT_SCHEMA,
    )
    async def create_project(args: dict) -> dict:
        return _result(_execute_create_project(
            db, args["name"], args["start_date"], args["end_date"],
            args.get("required_skills"),
        ))

    @tool(
        name="remember_fact",
        description=(
            "Store a user preference, habit, or note for future sessions. "
            "If a memory with this key already exists, it is updated."
        ),
        input_schema=_REMEMBER_FACT_SCHEMA,
    )
    async def remember_fact(args: dict) -> dict:
        return _result(_execute_remember_fact(
            db, user_id, args["category"], args["key"], args["value"],
            args.get("confidence", 3),
        ))

    @tool(
        name="list_memories",
        description=(
            "Retrieve all stored long-term memories about the user's preferences and habits. "
            "Call at the start of a new session or when you need to recall past context."
        ),
        input_schema=_LIST_MEMORIES_SCHEMA,
    )
    async def list_memories(args: dict) -> dict:
        return _result(_execute_list_memories(db, user_id, args.get("category")))

    return create_sdk_mcp_server("staffing", tools=[
        set_assignment,
        clear_assignment,
        get_availability,
        check_conflicts,
        suggest_data_scientists,
        update_data_scientist,
        update_project,
        create_data_scientist,
        create_project,
        remember_fact,
        list_memories,
    ])
