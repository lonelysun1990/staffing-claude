"""Seed the PostgreSQL database from the existing store.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .database import Base, SessionLocal, engine
from .orm_models import (
    AssignmentORM,
    ConfigORM,
    DataScientistORM,
    ProjectORM,
    ProjectWeekORM,
)


def seed():
    Base.metadata.create_all(bind=engine)
    store_path = Path(__file__).resolve().parent.parent / "data" / "store.json"
    if not store_path.exists():
        print("store.json not found, skipping seed")
        return

    data = json.loads(store_path.read_text())
    db = SessionLocal()
    try:
        if db.query(DataScientistORM).count() > 0:
            print("Database already has data, skipping seed")
            return

        # Config
        cfg = data.get("config", {})
        db.merge(ConfigORM(id=1, granularity_weeks=cfg.get("granularity_weeks", 1), horizon_weeks=cfg.get("horizon_weeks", 26)))

        # DS id remapping (store.json ids may not be sequential)
        ds_id_map: dict[int, int] = {}
        for ds in data.get("data_scientists", []):
            orm = DataScientistORM(
                name=ds["name"],
                level=ds.get("level", "DS"),
                max_concurrent_projects=ds.get("max_concurrent_projects", 1),
                efficiency=ds.get("efficiency", 1.0),
                notes=ds.get("notes"),
            )
            db.add(orm)
            db.flush()
            ds_id_map[ds["id"]] = orm.id

        # Projects
        project_id_map: dict[int, int] = {}
        for p in data.get("projects", []):
            orm = ProjectORM(
                name=p["name"],
                start_date=date.fromisoformat(p["start_date"]),
                end_date=date.fromisoformat(p["end_date"]),
            )
            db.add(orm)
            db.flush()
            project_id_map[p["id"]] = orm.id
            for week in p.get("fte_requirements", []):
                db.add(ProjectWeekORM(
                    project_id=orm.id,
                    week_start=date.fromisoformat(week["week_start"]),
                    fte=week["fte"],
                ))

        # Assignments
        for a in data.get("assignments", []):
            new_ds_id = ds_id_map.get(a["data_scientist_id"])
            new_proj_id = project_id_map.get(a["project_id"])
            if new_ds_id and new_proj_id:
                db.add(AssignmentORM(
                    data_scientist_id=new_ds_id,
                    project_id=new_proj_id,
                    week_start=date.fromisoformat(a["week_start"]),
                    allocation=a["allocation"],
                ))

        db.commit()
        print(f"Seeded {len(ds_id_map)} data scientists, {len(project_id_map)} projects, {len(data.get('assignments', []))} assignments")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
