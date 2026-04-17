"""Load store.json fixtures into the DB for eval isolation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.storage import import_full_json


def load_eval_fixture(db: Session, fixture_path: Path) -> None:
    """Replace scheduling data with the given store.json-format file."""
    data: dict[str, Any] = json.loads(fixture_path.read_text())
    import_full_json(db, data)
