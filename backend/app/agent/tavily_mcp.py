"""
Tavily MCP wiring for ClaudeAgentOptions.

Remote HTTP (default): no Node.js required — best for Railway.
Optional stdio via npx: set TAVILY_MCP_TRANSPORT=stdio and install Node 20+.

Tool names match tavily-mcp (github.com/tavily-ai/tavily-mcp); qualified as mcp__tavily__<name>.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

# Server key in mcp_servers dict — must match tool prefix mcp__tavily__*
TAVILY_SERVER_KEY = "tavily"

# Exposed by tavily-mcp (local or remote)
TAVILY_TOOL_SHORT_NAMES: tuple[str, ...] = (
    "tavily_search",
    "tavily_extract",
    "tavily_crawl",
    "tavily_map",
    "tavily_research",
)


def tavily_qualified_tool_name(short: str) -> str:
    return f"mcp__{TAVILY_SERVER_KEY}__{short}"


TAVILY_MCP_TOOL_NAMES: list[str] = [tavily_qualified_tool_name(s) for s in TAVILY_TOOL_SHORT_NAMES]


def tavily_api_key_configured() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY", "").strip())


def tavily_mcp_server_config(api_key: str) -> dict[str, Any]:
    """
    Build MCP server entry for mcp_servers[\"tavily\"].

    TAVILY_MCP_TRANSPORT:
      - http (default): remote https://mcp.tavily.com — no Node
      - sse: same host, SSE transport (try if http fails with your SDK)
      - stdio: npx tavily-mcp (needs Node/npm on PATH)
    """
    key = api_key.strip()
    transport = os.environ.get("TAVILY_MCP_TRANSPORT", "http").lower().strip()

    if transport == "stdio":
        pkg = os.environ.get("TAVILY_MCP_NPX_PACKAGE", "tavily-mcp@0.2.18")
        args_raw = os.environ.get("TAVILY_MCP_NPX_ARGS", "").strip()
        if args_raw:
            npx_args = args_raw.split()
        else:
            npx_args = ["-y", pkg]
        env = {"TAVILY_API_KEY": key, **_default_parameters_env()}
        return {
            "type": "stdio",
            "command": os.environ.get("TAVILY_MCP_NPX_COMMAND", "npx"),
            "args": npx_args,
            "env": env,
        }

    # Remote MCP (Tavily-hosted): streamable HTTP or SSE
    q = quote(key, safe="")
    url = f"https://mcp.tavily.com/mcp/?tavilyApiKey={q}"
    headers: dict[str, str] = {}
    dp = os.environ.get("TAVILY_DEFAULT_PARAMETERS_JSON", "").strip()
    if dp:
        headers["DEFAULT_PARAMETERS"] = dp

    if transport == "sse":
        out: dict[str, Any] = {"type": "sse", "url": url}
        if headers:
            out["headers"] = headers
        return out

    out = {"type": "http", "url": url}
    if headers:
        out["headers"] = headers
    return out


def _default_parameters_env() -> dict[str, str]:
    """Optional env vars copied into stdio server env (see Tavily docs)."""
    out: dict[str, str] = {}
    dp = os.environ.get("TAVILY_DEFAULT_PARAMETERS_JSON", "").strip()
    if dp:
        out["DEFAULT_PARAMETERS"] = dp
    return out
