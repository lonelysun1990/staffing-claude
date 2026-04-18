"""Eval rubrics — no app.agent / SDK imports (safe for lightweight unit tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


def load_case(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "id" not in data:
        raise ValueError(f"Invalid case file (missing id): {path}")
    if "turns" in data:
        if not isinstance(data["turns"], list) or not data["turns"]:
            raise ValueError(f"Invalid turns in {path}")
        return data
    if "user_message" not in data:
        raise ValueError(f"Need user_message or turns: {path}")
    return data


def session_id_from_events(events: List[Dict[str, Any]]) -> Any:
    """Return session_id from the terminal done event, if present."""
    for e in reversed(events):
        if e.get("type") == "done" and e.get("session_id") is not None:
            return e["session_id"]
    return None


def tool_names_from_events(events: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for e in events:
        if e.get("type") == "tool_call_start" and e.get("name"):
            out.append(str(e["name"]))
    return out


def assistant_text_from_events(events: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for e in events:
        if e.get("type") == "text_delta" and e.get("delta"):
            parts.append(str(e["delta"]))
    return "".join(parts)


def build_synthetic_events(tool_names: List[str], text: str) -> List[Dict[str, Any]]:
    """Rebuild events so check_expectations can score merged thread outputs."""
    ev: List[Dict[str, Any]] = []
    for n in tool_names:
        ev.append({"type": "tool_call_start", "name": n})
    if text:
        ev.append({"type": "text_delta", "delta": text})
    return ev


def check_expectations(
    events: List[Dict[str, Any]],
    expect: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]], float]:
    checks: List[Dict[str, Any]] = []
    weights: List[float] = []
    tools = tool_names_from_events(events)
    text = assistant_text_from_events(events)

    must = expect.get("must_call_tools") or expect.get("tools_called_include") or []
    for sub in must:
        ok = any(sub in t for t in tools)
        checks.append({"name": f"must_call:{sub}", "passed": ok})
        weights.append(1.0)

    forbid = expect.get("must_not_call_tools") or []
    for sub in forbid:
        ok = not any(sub in t for t in tools)
        checks.append({"name": f"must_not:{sub}", "passed": ok})
        weights.append(1.0)

    mn = expect.get("min_tool_calls")
    if mn is not None:
        ok = len(tools) >= int(mn)
        checks.append({"name": "min_tool_calls", "passed": ok, "got": len(tools), "limit": mn})
        weights.append(1.0)

    mx = expect.get("max_tool_calls")
    if mx is not None:
        ok = len(tools) <= int(mx)
        checks.append({"name": "max_tool_calls", "passed": ok, "got": len(tools), "limit": mx})
        weights.append(1.0)

    for s in expect.get("response_contains") or []:
        ok = s in text
        checks.append({"name": f"response_contains:{s[:40]}", "passed": ok})
        weights.append(1.0)

    if not checks:
        checks.append({"name": "noop", "passed": True})
        weights.append(1.0)

    passed_all = all(c["passed"] for c in checks)
    score = sum(weights[i] for i, c in enumerate(checks) if c["passed"]) / sum(weights) if weights else 1.0
    return passed_all, checks, score
