from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from .models import (
    Assignment,
    AssignmentCreate,
    AssignmentsPayload,
    ConfigModel,
    ConfigUpdate,
    DataScientist,
    DataScientistCreate,
    ImportResult,
    Project,
    ProjectCreate,
    ProjectWeek,
)
from .orm_models import (
    AssignmentORM,
    AuditLogORM,
    ConfigORM,
    DataScientistORM,
    DataScientistSkillORM,
    ProjectORM,
    ProjectSkillORM,
    ProjectWeekORM,
)


# ------------------------------------------------------------------ #
# Helpers to convert ORM → Pydantic
# ------------------------------------------------------------------ #

def _ds_to_schema(orm: DataScientistORM) -> DataScientist:
    return DataScientist(
        id=orm.id,
        name=orm.name,
        level=orm.level,
        max_concurrent_projects=orm.max_concurrent_projects,
        efficiency=orm.efficiency,
        notes=orm.notes,
        skills=[s.skill for s in (orm.skills or [])],
    )


def _project_to_schema(orm: ProjectORM) -> Project:
    return Project(
        id=orm.id,
        name=orm.name,
        start_date=orm.start_date,
        end_date=orm.end_date,
        fte_requirements=[
            ProjectWeek(week_start=w.week_start, fte=w.fte)
            for w in sorted(orm.fte_requirements, key=lambda x: x.week_start)
        ],
        required_skills=[s.skill for s in (orm.required_skills or [])],
    )


def _assignment_to_schema(orm: AssignmentORM) -> Assignment:
    return Assignment(
        id=orm.id,
        data_scientist_id=orm.data_scientist_id,
        project_id=orm.project_id,
        week_start=orm.week_start,
        allocation=orm.allocation,
    )


# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #

def get_config(db: Session) -> ConfigModel:
    cfg = db.query(ConfigORM).first()
    if not cfg:
        cfg = ConfigORM(id=1, granularity_weeks=1, horizon_weeks=26)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return ConfigModel(granularity_weeks=cfg.granularity_weeks, horizon_weeks=cfg.horizon_weeks)


def update_config(db: Session, payload: ConfigUpdate) -> ConfigModel:
    cfg = db.query(ConfigORM).first()
    if not cfg:
        cfg = ConfigORM(id=1, granularity_weeks=1, horizon_weeks=26)
        db.add(cfg)
    if payload.granularity_weeks is not None:
        cfg.granularity_weeks = payload.granularity_weeks
    if payload.horizon_weeks is not None:
        cfg.horizon_weeks = payload.horizon_weeks
    db.commit()
    db.refresh(cfg)
    return ConfigModel(granularity_weeks=cfg.granularity_weeks, horizon_weeks=cfg.horizon_weeks)


# ------------------------------------------------------------------ #
# Data scientists
# ------------------------------------------------------------------ #

def list_data_scientists(db: Session) -> List[DataScientist]:
    return [_ds_to_schema(ds) for ds in db.query(DataScientistORM).all()]


def create_data_scientist(db: Session, payload: DataScientistCreate) -> DataScientist:
    orm = DataScientistORM(
        name=payload.name,
        level=payload.level,
        max_concurrent_projects=payload.max_concurrent_projects,
        efficiency=payload.efficiency,
        notes=payload.notes,
    )
    db.add(orm)
    db.flush()
    for skill in (payload.skills or []):
        db.add(DataScientistSkillORM(data_scientist_id=orm.id, skill=skill))
    db.commit()
    db.refresh(orm)
    return _ds_to_schema(orm)


def update_data_scientist(db: Session, ds_id: int, payload: DataScientistCreate) -> DataScientist:
    orm = db.query(DataScientistORM).filter(DataScientistORM.id == ds_id).first()
    if not orm:
        raise KeyError(f"Data scientist {ds_id} not found")
    orm.name = payload.name
    orm.level = payload.level
    orm.max_concurrent_projects = payload.max_concurrent_projects
    orm.efficiency = payload.efficiency
    orm.notes = payload.notes
    db.query(DataScientistSkillORM).filter(DataScientistSkillORM.data_scientist_id == ds_id).delete()
    for skill in (payload.skills or []):
        db.add(DataScientistSkillORM(data_scientist_id=ds_id, skill=skill))
    db.commit()
    db.refresh(orm)
    return _ds_to_schema(orm)


def delete_data_scientist(db: Session, ds_id: int) -> None:
    orm = db.query(DataScientistORM).filter(DataScientistORM.id == ds_id).first()
    if not orm:
        raise KeyError(f"Data scientist {ds_id} not found")
    db.delete(orm)
    db.commit()


# ------------------------------------------------------------------ #
# Projects
# ------------------------------------------------------------------ #

def list_projects(db: Session) -> List[Project]:
    return [_project_to_schema(p) for p in db.query(ProjectORM).all()]


def create_project(db: Session, payload: ProjectCreate) -> Project:
    orm = ProjectORM(
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(orm)
    db.flush()
    for week in payload.fte_requirements:
        db.add(ProjectWeekORM(project_id=orm.id, week_start=week.week_start, fte=week.fte))
    for skill in (payload.required_skills or []):
        db.add(ProjectSkillORM(project_id=orm.id, skill=skill))
    db.commit()
    db.refresh(orm)
    return _project_to_schema(orm)


def update_project(db: Session, project_id: int, payload: ProjectCreate) -> Project:
    orm = db.query(ProjectORM).filter(ProjectORM.id == project_id).first()
    if not orm:
        raise KeyError(f"Project {project_id} not found")
    orm.name = payload.name
    orm.start_date = payload.start_date
    orm.end_date = payload.end_date
    db.query(ProjectWeekORM).filter(ProjectWeekORM.project_id == project_id).delete()
    for week in payload.fte_requirements:
        db.add(ProjectWeekORM(project_id=project_id, week_start=week.week_start, fte=week.fte))
    db.query(ProjectSkillORM).filter(ProjectSkillORM.project_id == project_id).delete()
    for skill in (payload.required_skills or []):
        db.add(ProjectSkillORM(project_id=project_id, skill=skill))
    db.commit()
    db.refresh(orm)
    return _project_to_schema(orm)


def delete_project(db: Session, project_id: int) -> None:
    orm = db.query(ProjectORM).filter(ProjectORM.id == project_id).first()
    if not orm:
        raise KeyError(f"Project {project_id} not found")
    db.delete(orm)
    db.commit()


# ------------------------------------------------------------------ #
# Assignments
# ------------------------------------------------------------------ #

def list_assignments(db: Session) -> List[Assignment]:
    return [_assignment_to_schema(a) for a in db.query(AssignmentORM).all()]


def add_assignment(db: Session, payload: AssignmentCreate, changed_by: str = "system") -> Assignment:
    ds = db.query(DataScientistORM).filter(DataScientistORM.id == payload.data_scientist_id).first()
    if not ds:
        raise KeyError(f"Data scientist {payload.data_scientist_id} not found")
    project = db.query(ProjectORM).filter(ProjectORM.id == payload.project_id).first()
    if not project:
        raise KeyError(f"Project {payload.project_id} not found")

    orm = AssignmentORM(
        data_scientist_id=payload.data_scientist_id,
        project_id=payload.project_id,
        week_start=payload.week_start,
        allocation=payload.allocation,
    )
    db.add(orm)
    db.flush()
    db.add(AuditLogORM(
        assignment_id=orm.id,
        action="created",
        changed_by=changed_by,
        changed_at=datetime.utcnow().isoformat(),
        details=json.dumps(payload.model_dump(mode="json")),
    ))
    db.commit()
    db.refresh(orm)
    return _assignment_to_schema(orm)


def delete_assignment(db: Session, assignment_id: int, changed_by: str = "system") -> None:
    orm = db.query(AssignmentORM).filter(AssignmentORM.id == assignment_id).first()
    if not orm:
        raise KeyError(f"Assignment {assignment_id} not found")
    db.add(AuditLogORM(
        assignment_id=None,
        action="deleted",
        changed_by=changed_by,
        changed_at=datetime.utcnow().isoformat(),
        details=json.dumps(_assignment_to_schema(orm).model_dump(mode="json")),
    ))
    db.delete(orm)
    db.commit()


def bulk_remove_assignments(
    db: Session,
    data_scientist_id: Optional[int] = None,
    project_id: Optional[int] = None,
    week_start=None,
    start_date=None,
    end_date=None,
    changed_by: str = "system",
) -> int:
    """Delete assignments matching the given filters and return the count removed."""
    query = db.query(AssignmentORM)
    if data_scientist_id is not None:
        query = query.filter(AssignmentORM.data_scientist_id == data_scientist_id)
    if project_id is not None:
        query = query.filter(AssignmentORM.project_id == project_id)
    if week_start is not None:
        query = query.filter(AssignmentORM.week_start == week_start)
    if start_date is not None:
        query = query.filter(AssignmentORM.week_start >= start_date)
    if end_date is not None:
        query = query.filter(AssignmentORM.week_start <= end_date)

    to_delete = query.all()
    for orm in to_delete:
        db.add(AuditLogORM(
            assignment_id=None,
            action="deleted",
            changed_by=changed_by,
            changed_at=datetime.utcnow().isoformat(),
            details=json.dumps(_assignment_to_schema(orm).model_dump(mode="json")),
        ))
        db.delete(orm)
    db.commit()
    return len(to_delete)


def replace_assignments(db: Session, payload: AssignmentsPayload) -> List[Assignment]:
    for item in payload.assignments:
        if not db.query(DataScientistORM).filter(DataScientistORM.id == item.data_scientist_id).first():
            raise KeyError(f"Data scientist {item.data_scientist_id} not found")
        if not db.query(ProjectORM).filter(ProjectORM.id == item.project_id).first():
            raise KeyError(f"Project {item.project_id} not found")

    db.query(AuditLogORM).filter(AuditLogORM.assignment_id.isnot(None)).update({"assignment_id": None})
    db.query(AssignmentORM).delete()
    new_assignments = []
    for item in payload.assignments:
        orm = AssignmentORM(
            data_scientist_id=item.data_scientist_id,
            project_id=item.project_id,
            week_start=item.week_start,
            allocation=item.allocation,
        )
        db.add(orm)
        new_assignments.append(orm)
    db.commit()
    return [_assignment_to_schema(a) for a in new_assignments]


# ------------------------------------------------------------------ #
# Capacity conflict detection
# ------------------------------------------------------------------ #

def get_conflicts(db: Session) -> List[dict]:
    """Return weeks where a DS is assigned > 100% total allocation."""
    assignments = db.query(AssignmentORM).all()
    weekly: Dict[tuple, float] = {}
    for a in assignments:
        key = (a.data_scientist_id, a.week_start)
        weekly[key] = weekly.get(key, 0.0) + a.allocation

    conflicts = []
    for (ds_id, week_start), total in weekly.items():
        if total > 1.0:
            ds = db.query(DataScientistORM).filter(DataScientistORM.id == ds_id).first()
            conflicts.append({
                "data_scientist_id": ds_id,
                "data_scientist_name": ds.name if ds else str(ds_id),
                "week_start": week_start.isoformat(),
                "total_allocation": round(total, 3),
                "over_by": round(total - 1.0, 3),
            })
    return sorted(conflicts, key=lambda x: (x["week_start"], x["data_scientist_name"]))


# ------------------------------------------------------------------ #
# Skills
# ------------------------------------------------------------------ #

def list_skills(db: Session) -> List[str]:
    rows = db.query(DataScientistSkillORM.skill).distinct().all()
    return sorted(set(r.skill for r in rows))


def get_skill_suggestions(db: Session, project_id: int) -> List[DataScientist]:
    """Return DSs whose skills match the project's required skills, ordered by availability."""
    project = db.query(ProjectORM).filter(ProjectORM.id == project_id).first()
    if not project:
        raise KeyError(f"Project {project_id} not found")

    required = {s.skill for s in project.required_skills}
    all_ds = db.query(DataScientistORM).all()

    scored = []
    for ds in all_ds:
        ds_skills = {s.skill for s in ds.skills}
        match_count = len(required & ds_skills) if required else 0
        scored.append((match_count, ds))

    scored.sort(key=lambda x: -x[0])
    return [_ds_to_schema(ds) for _, ds in scored]


# ------------------------------------------------------------------ #
# Audit log
# ------------------------------------------------------------------ #

def list_audit_logs(db: Session, limit: int = 100) -> List[dict]:
    rows = (
        db.query(AuditLogORM)
        .order_by(AuditLogORM.changed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "assignment_id": r.assignment_id,
            "action": r.action,
            "changed_by": r.changed_by,
            "changed_at": r.changed_at,
            "details": json.loads(r.details) if r.details else None,
        }
        for r in rows
    ]


# ------------------------------------------------------------------ #
# Import/export
# ------------------------------------------------------------------ #

def export_assignments(db: Session) -> str:
    assignments = db.query(AssignmentORM).all()
    ds_lookup = {ds.id: ds for ds in db.query(DataScientistORM).all()}
    project_lookup = {p.id: p for p in db.query(ProjectORM).all()}
    rows = []
    for a in assignments:
        ds = ds_lookup.get(a.data_scientist_id)
        project = project_lookup.get(a.project_id)
        rows.append({
            "week_start": a.week_start.isoformat(),
            "data_scientist": ds.name if ds else a.data_scientist_id,
            "project": project.name if project else a.project_id,
            "allocation": a.allocation,
            "efficiency": ds.efficiency if ds else None,
        })
    return pd.DataFrame(rows).to_csv(index=False)


def import_from_file(db: Session, file_path: Path) -> ImportResult:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    required_columns = {"week_start", "data_scientist", "project", "allocation"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    replaced_ds = db.query(DataScientistORM).count()
    replaced_projects = db.query(ProjectORM).count()
    replaced_assignments = db.query(AssignmentORM).count()

    db.query(AssignmentORM).delete()
    db.query(ProjectWeekORM).delete()
    db.query(ProjectORM).delete()
    db.query(DataScientistORM).delete()
    db.commit()

    ds_map: Dict[str, DataScientistORM] = {}
    project_map: Dict[str, ProjectORM] = {}
    created_ds = created_projects = 0

    for _, row in df.iterrows():
        week_start = pd.to_datetime(row["week_start"]).date()
        allocation = float(row["allocation"])
        ds_name = str(row["data_scientist"]).strip()
        project_name = str(row["project"]).strip()

        if ds_name not in ds_map:
            orm = DataScientistORM(
                name=ds_name,
                level=str(row.get("level", "Imported DS")) if pd.notna(row.get("level")) else "Imported DS",
                max_concurrent_projects=int(row.get("max_concurrent_projects", 2)) if pd.notna(row.get("max_concurrent_projects")) else 2,
                efficiency=float(row.get("efficiency", 1.0)) if pd.notna(row.get("efficiency")) else 1.0,
            )
            db.add(orm)
            db.flush()
            ds_map[ds_name] = orm
            created_ds += 1

        if project_name not in project_map:
            start_date = pd.to_datetime(row.get("project_start")).date() if pd.notna(row.get("project_start")) else week_start
            end_date = pd.to_datetime(row.get("project_end")).date() if pd.notna(row.get("project_end")) else (start_date + timedelta(weeks=12))
            fte_value = float(row.get("fte", allocation)) if pd.notna(row.get("fte")) else allocation
            project_orm = ProjectORM(name=project_name, start_date=start_date, end_date=end_date)
            db.add(project_orm)
            db.flush()
            for i in range(max(1, int(((end_date - start_date).days // 7) + 1))):
                db.add(ProjectWeekORM(project_id=project_orm.id, week_start=start_date + timedelta(weeks=i), fte=fte_value))
            project_map[project_name] = project_orm
            created_projects += 1

        db.add(AssignmentORM(
            data_scientist_id=ds_map[ds_name].id,
            project_id=project_map[project_name].id,
            week_start=week_start,
            allocation=allocation,
        ))

    db.commit()
    created_assignments = db.query(AssignmentORM).count()

    return ImportResult(
        created_data_scientists=created_ds,
        created_projects=created_projects,
        created_assignments=created_assignments,
        replaced_existing_assignments=replaced_assignments,
    )
