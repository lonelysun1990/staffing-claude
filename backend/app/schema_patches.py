"""
Apply additive DB changes when the ORM gains columns/tables.

`Base.metadata.create_all()` creates missing tables but does not ALTER existing
tables. Production Postgres (and local SQLite) need explicit patches.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_runtime_schema_patches(engine: Engine) -> None:
    """Idempotent patches safe to run every startup."""
    insp = inspect(engine)
    if not insp.has_table("dynamic_tools"):
        return

    col_names = {c["name"] for c in insp.get_columns("dynamic_tools")}
    alters: list[str] = []
    if "code_revision" not in col_names:
        alters.append(
            "ALTER TABLE dynamic_tools ADD COLUMN code_revision INTEGER NOT NULL DEFAULT 0"
        )

    if not alters:
        return

    with engine.begin() as conn:
        for sql in alters:
            conn.execute(text(sql))
