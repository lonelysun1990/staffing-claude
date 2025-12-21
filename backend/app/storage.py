from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

import pandas as pd

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
from .seed import build_seed_data, start_of_week


class Store:
    """Lightweight JSON-backed persistence layer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()
        self._ensure_seed_file()
        self._load()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ensure_seed_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            return

        seed = build_seed_data()
        data_scientists = [
            {"id": idx + 1, **payload} for idx, payload in enumerate(seed["data_scientists"])
        ]
        projects = [{"id": idx + 1, **payload} for idx, payload in enumerate(seed["projects"])]
        assignments = [
            {"id": idx + 1, **payload} for idx, payload in enumerate(seed["assignments"])
        ]

        state = {
            "config": seed["config"],
            "data_scientists": data_scientists,
            "projects": projects,
            "assignments": assignments,
            "counters": {
                "data_scientists": len(data_scientists),
                "projects": len(projects),
                "assignments": len(assignments),
            },
        }
        self.path.write_text(json.dumps(state, indent=2))

    def _load(self) -> None:
        state = json.loads(self.path.read_text())
        counters = state.get("counters") or {}
        self.config = ConfigModel.model_validate(state.get("config", {}))
        self.data_scientists: List[DataScientist] = [
            DataScientist.model_validate(ds) for ds in state.get("data_scientists", [])
        ]
        self.projects: List[Project] = [
            Project.model_validate(
                {**project, "fte_requirements": project.get("fte_requirements", [])}
            )
            for project in state.get("projects", [])
        ]
        self.assignments: List[Assignment] = [
            Assignment.model_validate(a) for a in state.get("assignments", [])
        ]
        self.counters = {
            "data_scientists": counters.get("data_scientists", len(self.data_scientists)),
            "projects": counters.get("projects", len(self.projects)),
            "assignments": counters.get("assignments", len(self.assignments)),
        }

    def _save(self) -> None:
        state = {
            "config": self.config.model_dump(),
            "data_scientists": [ds.model_dump() for ds in self.data_scientists],
            "projects": [
                {
                    **project.model_dump(),
                    "fte_requirements": [
                        {"week_start": week.week_start.isoformat(), "fte": week.fte}
                        for week in project.fte_requirements
                    ],
                }
                for project in self.projects
            ],
            "assignments": [
                {**assignment.model_dump(), "week_start": assignment.week_start.isoformat()}
                for assignment in self.assignments
            ],
            "counters": self.counters,
        }
        self.path.write_text(json.dumps(state, indent=2))

    def _next_id(self, key: str) -> int:
        self.counters[key] += 1
        return self.counters[key]

    def _require_data_scientist(self, ds_id: int) -> DataScientist:
        for ds in self.data_scientists:
            if ds.id == ds_id:
                return ds
        raise KeyError(f"Data scientist {ds_id} not found")

    def _require_project(self, project_id: int) -> Project:
        for project in self.projects:
            if project.id == project_id:
                return project
        raise KeyError(f"Project {project_id} not found")

    # ------------------------------------------------------------------ #
    # Config operations
    # ------------------------------------------------------------------ #
    def get_config(self) -> ConfigModel:
        return self.config

    def update_config(self, payload: ConfigUpdate) -> ConfigModel:
        with self.lock:
            new_config = self.config.model_copy(update=payload.model_dump(exclude_unset=True))
            self.config = ConfigModel.model_validate(new_config)
            self._save()
        return self.config

    # ------------------------------------------------------------------ #
    # Data scientist operations
    # ------------------------------------------------------------------ #
    def list_data_scientists(self) -> List[DataScientist]:
        return self.data_scientists

    def create_data_scientist(self, payload: DataScientistCreate) -> DataScientist:
        with self.lock:
            new_ds = DataScientist(id=self._next_id("data_scientists"), **payload.model_dump())
            self.data_scientists.append(new_ds)
            self._save()
        return new_ds

    def update_data_scientist(self, ds_id: int, payload: DataScientistCreate) -> DataScientist:
        with self.lock:
            updated = None
            for idx, ds in enumerate(self.data_scientists):
                if ds.id == ds_id:
                    updated = DataScientist(id=ds_id, **payload.model_dump())
                    self.data_scientists[idx] = updated
                    break
            if not updated:
                raise KeyError(f"Data scientist {ds_id} not found")
            self._save()
        return updated

    def delete_data_scientist(self, ds_id: int) -> None:
        with self.lock:
            before = len(self.data_scientists)
            self.data_scientists = [ds for ds in self.data_scientists if ds.id != ds_id]
            if before == len(self.data_scientists):
                raise KeyError(f"Data scientist {ds_id} not found")
            self.assignments = [a for a in self.assignments if a.data_scientist_id != ds_id]
            self._save()

    # ------------------------------------------------------------------ #
    # Project operations
    # ------------------------------------------------------------------ #
    def list_projects(self) -> List[Project]:
        return self.projects

    def create_project(self, payload: ProjectCreate) -> Project:
        with self.lock:
            fte_requirements = [
                ProjectWeek.model_validate(week) for week in payload.fte_requirements
            ]
            new_project = Project(
                id=self._next_id("projects"),
                name=payload.name,
                start_date=payload.start_date,
                end_date=payload.end_date,
                fte_requirements=fte_requirements,
            )
            self.projects.append(new_project)
            self._save()
        return new_project

    def update_project(self, project_id: int, payload: ProjectCreate) -> Project:
        with self.lock:
            updated = None
            for idx, project in enumerate(self.projects):
                if project.id == project_id:
                    updated = Project(
                        id=project_id,
                        name=payload.name,
                        start_date=payload.start_date,
                        end_date=payload.end_date,
                        fte_requirements=[
                            ProjectWeek.model_validate(week) for week in payload.fte_requirements
                        ],
                    )
                    self.projects[idx] = updated
                    break
            if not updated:
                raise KeyError(f"Project {project_id} not found")
            self._save()
        return updated

    def delete_project(self, project_id: int) -> None:
        with self.lock:
            before = len(self.projects)
            self.projects = [p for p in self.projects if p.id != project_id]
            if before == len(self.projects):
                raise KeyError(f"Project {project_id} not found")
            self.assignments = [a for a in self.assignments if a.project_id != project_id]
            self._save()

    # ------------------------------------------------------------------ #
    # Assignment operations
    # ------------------------------------------------------------------ #
    def list_assignments(self) -> List[Assignment]:
        return self.assignments

    def replace_assignments(self, payload: AssignmentsPayload) -> List[Assignment]:
        with self.lock:
            validated = []
            for assignment in payload.assignments:
                # Ensure references exist
                self._require_data_scientist(assignment.data_scientist_id)
                self._require_project(assignment.project_id)
                validated.append(assignment)

            self.assignments = [
                Assignment(
                    id=index + 1,  # deterministic ordering
                    data_scientist_id=item.data_scientist_id,
                    project_id=item.project_id,
                    week_start=item.week_start,
                    allocation=item.allocation,
                )
                for index, item in enumerate(validated)
            ]
            self.counters["assignments"] = len(self.assignments)
            self._save()
        return self.assignments

    # ------------------------------------------------------------------ #
    # Import/export helpers
    # ------------------------------------------------------------------ #
    def export_assignments(self) -> str:
        ds_lookup = {ds.id: ds for ds in self.data_scientists}
        project_lookup = {project.id: project for project in self.projects}
        rows = []
        for assignment in self.assignments:
            ds = ds_lookup.get(assignment.data_scientist_id)
            project = project_lookup.get(assignment.project_id)
            rows.append(
                {
                    "week_start": assignment.week_start.isoformat(),
                    "data_scientist": ds.name if ds else assignment.data_scientist_id,
                    "project": project.name if project else assignment.project_id,
                    "allocation": assignment.allocation,
                    "efficiency": ds.efficiency if ds else None,
                }
            )
        df = pd.DataFrame(rows)
        return df.to_csv(index=False)

    def import_from_file(self, file_path: Path) -> ImportResult:
        """Import schedule from Excel (.xlsx, .xls) or CSV file.
        
        This will clear all existing data_scientists, projects, and assignments
        to avoid conflicts with seed data.
        """
        # Detect file type and read accordingly
        suffix = file_path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(file_path)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}. Use .csv, .xlsx, or .xls")

        required_columns = {"week_start", "data_scientist", "project", "allocation"}
        missing_columns = required_columns - set(df.columns)
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

        with self.lock:
            # Clear all existing data to avoid conflicts with seed data
            replaced_ds = len(self.data_scientists)
            replaced_projects = len(self.projects)
            replaced_assignments = len(self.assignments)
            
            self.data_scientists = []
            self.projects = []
            self.assignments = []
            self.counters = {"data_scientists": 0, "projects": 0, "assignments": 0}

            created_ds = created_projects = 0
            new_assignments: List[AssignmentCreate] = []

            # Track unique data scientists and projects for creation
            ds_map: Dict[str, DataScientist] = {}
            project_map: Dict[str, Project] = {}

            for _, row in df.iterrows():
                week_start = pd.to_datetime(row["week_start"]).date()
                allocation = float(row["allocation"])
                ds_name = str(row["data_scientist"]).strip()
                project_name = str(row["project"]).strip()

                # Get or create data scientist
                if ds_name not in ds_map:
                    ds_payload = DataScientistCreate(
                        name=ds_name,
                        level=str(row.get("level", "Imported DS")) if pd.notna(row.get("level")) else "Imported DS",
                        max_concurrent_projects=int(row.get("max_concurrent_projects", 2)) if pd.notna(row.get("max_concurrent_projects")) else 2,
                        efficiency=float(row.get("efficiency", 1.0)) if pd.notna(row.get("efficiency")) else 1.0,
                    )
                    new_ds = DataScientist(id=self._next_id("data_scientists"), **ds_payload.model_dump())
                    self.data_scientists.append(new_ds)
                    ds_map[ds_name] = new_ds
                    created_ds += 1
                ds = ds_map[ds_name]

                # Get or create project
                if project_name not in project_map:
                    start_date = pd.to_datetime(row.get("project_start")).date() if pd.notna(row.get("project_start")) else week_start
                    end_date = pd.to_datetime(row.get("project_end")).date() if pd.notna(row.get("project_end")) else (start_date + timedelta(weeks=12))
                    fte_value = float(row.get("fte", allocation)) if pd.notna(row.get("fte")) else allocation

                    fte_requirements = [
                        ProjectWeek(week_start=start_date + timedelta(weeks=i), fte=fte_value)
                        for i in range(max(1, int(((end_date - start_date).days // 7) + 1)))
                    ]
                    new_project = Project(
                        id=self._next_id("projects"),
                        name=project_name,
                        start_date=start_date,
                        end_date=end_date,
                        fte_requirements=fte_requirements,
                    )
                    self.projects.append(new_project)
                    project_map[project_name] = new_project
                    created_projects += 1
                project = project_map[project_name]

                new_assignments.append(
                    AssignmentCreate(
                        data_scientist_id=ds.id,
                        project_id=project.id,
                        week_start=week_start,
                        allocation=allocation,
                    )
                )

            # Create assignments
            self.assignments = [
                Assignment(
                    id=index + 1,
                    data_scientist_id=item.data_scientist_id,
                    project_id=item.project_id,
                    week_start=item.week_start,
                    allocation=item.allocation,
                )
                for index, item in enumerate(new_assignments)
            ]
            self.counters["assignments"] = len(self.assignments)
            self._save()

        return ImportResult(
            created_data_scientists=created_ds,
            created_projects=created_projects,
            created_assignments=len(new_assignments),
            replaced_existing_assignments=replaced_assignments,
        )


_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if not _store:
        data_path = Path(__file__).resolve().parent.parent / "data" / "store.json"
        _store = Store(data_path)
    return _store

