"""
In-process MCP server for the staffing agent.

Each tool wraps an _execute_* function from executor.py via a closure that
captures the SQLAlchemy Session so tool handlers have direct DB access.

Call build_mcp_server(db, user_id, session_id) per request to get a McpSdkServerConfig
ready for ClaudeAgentOptions.mcp_servers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from claude_agent_sdk import create_sdk_mcp_server, tool, McpSdkServerConfig

from .tavily_mcp import TAVILY_MCP_TOOL_NAMES, tavily_api_key_configured

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
    _execute_store_artifact,
    _execute_get_ds_team_weekly_aggregates,
    _execute_create_dynamic_tool,
    _execute_update_dynamic_tool,
    _execute_list_dynamic_tools,
    _execute_delete_dynamic_tool,
    _execute_run_dynamic_tool,
    _execute_check_dynamic_tool_status,
    _execute_list_skills,
    _execute_get_skill,
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
    [mcp_tool_id(n) for n in (
        "get_availability",
        "check_conflicts",
        "suggest_data_scientists",
        "list_memories",
        "store_artifact",
        "get_ds_team_weekly_aggregates",
        "create_dynamic_tool",
        "update_dynamic_tool",
        "list_dynamic_tools",
        "delete_dynamic_tool",
        "run_dynamic_tool",
        "check_dynamic_tool_status",
        "list_skills",
        "get_skill",
    )]
    + TAVILY_MCP_TOOL_NAMES
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
        "store_artifact",
        "get_ds_team_weekly_aggregates",
        "create_dynamic_tool",
        "update_dynamic_tool",
        "list_dynamic_tools",
        "delete_dynamic_tool",
        "run_dynamic_tool",
        "check_dynamic_tool_status",
        "list_skills",
        "get_skill",
    )
]


def build_allowed_tool_names() -> list[str]:
    """Staffing MCP tools plus Tavily web tools when TAVILY_API_KEY is set."""
    names = list(ALL_TOOL_NAMES)
    if tavily_api_key_configured():
        names.extend(TAVILY_MCP_TOOL_NAMES)
    return names


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

_STORE_ARTIFACT_SCHEMA = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "description": "JSON blob referenced by artifact_id for run_dynamic_tool",
        },
        "ttl_minutes": {
            "type": "integer",
            "description": "TTL in minutes (default 60, max 1440)",
        },
    },
    "required": ["payload"],
}

_GET_DS_AGG_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

_CREATE_DYNAMIC_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Unique tool name (letters, digits, _, -)"},
        "description": {"type": "string"},
        "parameters_schema": {
            "type": "object",
            "description": "JSON Schema for kwargs passed to run()",
        },
        "code": {
            "type": "string",
            "description": "Python source defining run(**kwargs). Use matplotlib Agg for plots.",
        },
        "requirements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "pip requirements e.g. [\"matplotlib\"]",
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "description", "parameters_schema", "code"],
}

_UPDATE_DYNAMIC_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": ["string", "null"]},
        "parameters_schema": {"type": ["object", "null"]},
        "code": {"type": ["string", "null"]},
        "requirements": {"type": ["array", "null"], "items": {"type": "string"}},
        "tags": {"type": ["array", "null"], "items": {"type": "string"}},
    },
    "required": ["name"],
}

_LIST_DYNAMIC_TOOLS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

_DELETE_DYNAMIC_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}

_RUN_DYNAMIC_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "arguments": {
            "type": "object",
            "description": "Keyword arguments for run(); merged over artifact payload if artifact_id set",
        },
        "artifact_id": {
            "type": ["string", "null"],
            "description": "Optional artifact from store_artifact; dict payloads merge into arguments",
        },
    },
    "required": ["name"],
}

_CHECK_DYNAMIC_TOOL_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "max_wait_seconds": {
            "type": "integer",
            "description": (
                "If >0, wait (blocking) until env is ready/failed or timeout. "
                "Polls every poll_interval_seconds. Typical after create/update: 120. "
                "Use 0 for an instant snapshot only."
            ),
        },
        "poll_interval_seconds": {
            "type": "number",
            "description": "Seconds between polls while waiting; default 10. Ignored when max_wait_seconds is 0.",
        },
    },
    "required": ["name"],
}

_LIST_SKILLS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
}

_GET_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_id": {
            "type": "string",
            "description": "Skill directory id (from list_skills), e.g. staffing-analytics-charts",
        },
    },
    "required": ["skill_id"],
}


# ---------------------------------------------------------------------------
# Per-request MCP server factory
# ---------------------------------------------------------------------------

def build_mcp_server(
    db: Session,
    user_id: Optional[int],
    session_id: Optional[int] = None,
) -> McpSdkServerConfig:
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

    @tool(
        name="store_artifact",
        description=(
            "Store a compact JSON payload server-side and get an artifact_id. "
            "Use with run_dynamic_tool to avoid passing large data in chat. "
            "Payloads expire after ttl_minutes."
        ),
        input_schema=_STORE_ARTIFACT_SCHEMA,
    )
    async def store_artifact_tool(args: dict) -> dict:
        return _result(
            _execute_store_artifact(
                db,
                user_id,
                session_id,
                args["payload"],
                args.get("ttl_minutes"),
            ),
        )

    @tool(
        name="get_ds_team_weekly_aggregates",
        description=(
            "Returns weekly team average allocation %% for all data scientists over the planning horizon. "
            "Small JSON for charts — prefer this over raw get_availability for plotting."
        ),
        input_schema=_GET_DS_AGG_SCHEMA,
    )
    async def get_ds_team_weekly_aggregates(args: dict) -> dict:
        return _result(_execute_get_ds_team_weekly_aggregates(db))

    @tool(
        name="create_dynamic_tool",
        description=(
            "Register a Python tool with its own venv and pip requirements. "
            "Code must define run(**kwargs). After create, either call "
            "check_dynamic_tool_status(name, max_wait_seconds=120) once, or call run_dynamic_tool "
            "(it waits for the venv). On failure use update_dynamic_tool to fix and override."
        ),
        input_schema=_CREATE_DYNAMIC_TOOL_SCHEMA,
    )
    async def create_dynamic_tool(args: dict) -> dict:
        return _result(
            _execute_create_dynamic_tool(
                db,
                args["name"],
                args["description"],
                args["parameters_schema"],
                args["code"],
                args.get("requirements"),
                args.get("tags"),
            ),
        )

    @tool(
        name="update_dynamic_tool",
        description=(
            "Replace an existing dynamic tool by name (code, schema, requirements). "
            "Bumps code_revision; reinstalls venv if requirements change."
        ),
        input_schema=_UPDATE_DYNAMIC_TOOL_SCHEMA,
    )
    async def update_dynamic_tool(args: dict) -> dict:
        return _result(
            _execute_update_dynamic_tool(
                db,
                args["name"],
                args.get("description"),
                args.get("parameters_schema"),
                args.get("code"),
                args.get("requirements"),
                args.get("tags"),
            ),
        )

    @tool(
        name="list_dynamic_tools",
        description="List registered dynamic tools and their env_status.",
        input_schema=_LIST_DYNAMIC_TOOLS_SCHEMA,
    )
    async def list_dynamic_tools(args: dict) -> dict:
        return _result(_execute_list_dynamic_tools(db))

    @tool(
        name="delete_dynamic_tool",
        description="Remove a dynamic tool and delete its virtual environment.",
        input_schema=_DELETE_DYNAMIC_TOOL_SCHEMA,
    )
    async def delete_dynamic_tool(args: dict) -> dict:
        return _result(_execute_delete_dynamic_tool(db, args["name"]))

    @tool(
        name="run_dynamic_tool",
        description=(
            "Execute a registered dynamic tool in its venv. Returns small JSON (result or structured error). "
            "Blocks up to ~2 minutes if the tool venv is still installing (same wait as status check). "
            "For matplotlib plots, return {\"type\": \"png_base64\", \"data\": \"<base64>\"} from run() — "
            "the server stores the image and returns {\"type\": \"image\", \"image_id\": \"...\"} for the chat UI. "
            "Always run after create/update to verify."
        ),
        input_schema=_RUN_DYNAMIC_TOOL_SCHEMA,
    )
    async def run_dynamic_tool(args: dict) -> dict:
        return _result(
            _execute_run_dynamic_tool(
                db,
                args["name"],
                args.get("arguments"),
                args.get("artifact_id"),
                user_id,
                session_id,
            ),
        )

    @tool(
        name="check_dynamic_tool_status",
        description=(
            "Read env_status for a dynamic tool (instant if max_wait_seconds=0). "
            "After create/update with new requirements, prefer max_wait_seconds=120 (poll ~every 10s) "
            "instead of many rapid checks. run_dynamic_tool also waits for the venv."
        ),
        input_schema=_CHECK_DYNAMIC_TOOL_STATUS_SCHEMA,
    )
    async def check_dynamic_tool_status(args: dict) -> dict:
        return _result(
            _execute_check_dynamic_tool_status(
                db,
                args["name"],
                max(0, int(args.get("max_wait_seconds") or 0)),
                max(2.0, float(args.get("poll_interval_seconds") or 10.0)),
            ),
        )

    @tool(
        name="list_skills",
        description=(
            "List bundled playbook skills (markdown) shipped with the staffing agent. "
            "Each skill has an id and short description; use get_skill(skill_id) to load full instructions."
        ),
        input_schema=_LIST_SKILLS_SCHEMA,
    )
    async def list_skills_tool(args: dict) -> dict:
        return _result(_execute_list_skills())

    @tool(
        name="get_skill",
        description=(
            "Load the full markdown body of a bundled skill by skill_id (from list_skills). "
            "Use before complex analytics or dynamic-tool workflows when a skill matches the task."
        ),
        input_schema=_GET_SKILL_SCHEMA,
    )
    async def get_skill_tool(args: dict) -> dict:
        return _result(_execute_get_skill(args["skill_id"]))

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
        store_artifact_tool,
        get_ds_team_weekly_aggregates,
        create_dynamic_tool,
        update_dynamic_tool,
        list_dynamic_tools,
        delete_dynamic_tool,
        run_dynamic_tool,
        check_dynamic_tool_status,
        list_skills_tool,
        get_skill_tool,
    ])
