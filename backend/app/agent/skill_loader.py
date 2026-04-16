"""
Load bundled agent skills from backend/app/agent/skills/<skill_id>/SKILL.md.

Skills are markdown with optional YAML frontmatter (name, description).
Used by list_skills / get_skill MCP tools — not Cursor-specific.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SKILL_FILENAME = "SKILL.md"
MAX_SKILL_CHARS = 96_000

_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"

# Safe directory name under skills/ (matches dynamic tool naming style)
_SKILL_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")


def skills_root() -> Path:
    return _SKILLS_ROOT


def _is_safe_skill_id(skill_id: str) -> bool:
    return bool(skill_id and _SKILL_ID_RE.match(skill_id))


def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Return (metadata dict, markdown body). Body excludes frontmatter."""
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text

    # ---\n ... \n---\n rest
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    return _parse_frontmatter(fm_block), body


def _parse_frontmatter(fm: str) -> dict[str, str]:
    """Minimal YAML subset: key: value and key: >- / > / | folded blocks."""
    out: dict[str, str] = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        if rest in (">-", ">", "|"):
            i += 1
            parts: list[str] = []
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                parts.append(lines[i].strip())
                i += 1
            out[key] = "\n".join(parts) if rest == "|" else " ".join(parts)
            continue

        out[key] = rest.strip().strip('"').strip("'")
        i += 1

    return out


def _skill_path(skill_id: str) -> Path | None:
    if not _is_safe_skill_id(skill_id):
        return None
    p = _SKILLS_ROOT / skill_id / SKILL_FILENAME
    try:
        p.resolve().relative_to(_SKILLS_ROOT.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def list_skills() -> list[dict[str, Any]]:
    """Discover skill ids and metadata for list_skills tool."""
    rows: list[dict[str, Any]] = []
    if not _SKILLS_ROOT.is_dir():
        return rows

    for child in sorted(_SKILLS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        sid = child.name
        if not _is_safe_skill_id(sid):
            continue
        path = child / SKILL_FILENAME
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _split_frontmatter(raw)
        title = meta.get("name") or sid
        desc = (meta.get("description") or "").strip()
        if not desc:
            # First non-empty line after optional # heading
            for ln in body.splitlines():
                s = ln.strip()
                if s.startswith("#"):
                    continue
                if s:
                    desc = s[:280]
                    break
        rows.append(
            {
                "id": sid,
                "name": title,
                "description": desc[:500],
            }
        )
    return rows


def get_skill_body(skill_id: str) -> tuple[bool, str]:
    """
    Returns (ok, message).
    On success, message is the playbook markdown (no frontmatter), optionally truncated.
    On failure, message is an error string without OK/ERROR prefix.
    """
    path = _skill_path(skill_id)
    if path is None:
        return False, f"Unknown or invalid skill id: {skill_id!r}"

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to read skill: {exc}"

    _meta, body = _split_frontmatter(raw)
    body = body.strip()
    if not body:
        return False, "Skill file is empty."

    if len(body) > MAX_SKILL_CHARS:
        body = (
            body[:MAX_SKILL_CHARS]
            + "\n\n[Truncated — skill exceeds maximum length for one tool response.]\n"
        )

    return True, body


def format_list_skills_ok() -> str:
    return "OK: " + json.dumps(list_skills(), indent=2)


def format_get_skill_ok(body: str) -> str:
    return "OK:\n\n" + body


def format_error(msg: str) -> str:
    return "ERROR: " + msg
