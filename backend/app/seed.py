from __future__ import annotations

import json
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class SeedSource(Enum):
    """Available seed data sources."""
    CSV = "csv"           # Load from pso_schedule.csv (default)
    EXCEL = "excel"       # Load from pso_schedule.xlsx
    JSON = "json"         # Load from data_scientists.json + project_templates.json


# Default seed source
DEFAULT_SEED_SOURCE = SeedSource.CSV


def start_of_week(day: date) -> date:
    """Return the Monday of the week for a given date."""
    return day - timedelta(days=day.weekday())


def load_data_scientists() -> List[Dict]:
    """Load data scientists from JSON file."""
    with open(DATA_DIR / "data_scientists.json", "r") as f:
        return json.load(f)


def load_project_templates() -> List[Dict]:
    """Load project templates from JSON file."""
    with open(DATA_DIR / "project_templates.json", "r") as f:
        return json.load(f)


def build_seed_data_from_json() -> Dict:
    """Generate seed data from JSON files (data_scientists.json + project_templates.json)."""
    today = start_of_week(date.today())

    data_scientists = load_data_scientists()
    project_templates = load_project_templates()

    projects: List[Dict] = []
    assignments: List[Dict] = []

    week_offset = 0
    for template in project_templates:
        name = template["name"]
        duration_weeks = template["duration_weeks"]
        base_fte = template["base_fte"]

        start = today + timedelta(weeks=week_offset)
        end = start + timedelta(weeks=duration_weeks - 1)
        fte_requirements = []
        for week in range(duration_weeks):
            intensity = base_fte + (0.25 if 4 <= week <= 8 else 0.0)
            fte_requirements.append(
                {"week_start": (start + timedelta(weeks=week)).isoformat(), "fte": round(intensity, 2)}
            )
        projects.append(
            {
                "name": name,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "fte_requirements": fte_requirements,
            }
        )
        week_offset = (week_offset + 3) % 10

    # Seed a few sample assignments for the first horizon month
    for i in range(6):
        week_start = (today + timedelta(weeks=i)).isoformat()
        assignments.extend(
            [
                {
                    "data_scientist_id": 1 + (i % 5),
                    "project_id": 1 + (i % 3),
                    "week_start": week_start,
                    "allocation": 0.5,
                },
                {
                    "data_scientist_id": 6 + (i % 4),
                    "project_id": 4 + (i % 3),
                    "week_start": week_start,
                    "allocation": 0.4,
                },
            ]
        )

    return {
        "config": {"granularity_weeks": 1, "horizon_weeks": 26},
        "data_scientists": data_scientists,
        "projects": projects,
        "assignments": assignments,
    }


def build_seed_data_from_schedule(file_path: Path) -> Dict:
    """Generate seed data from a schedule file (CSV or Excel).
    
    Extracts unique data scientists and projects from the schedule,
    and creates assignments based on the rows.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    # Extract unique data scientists
    ds_map: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        ds_name = str(row["data_scientist"]).strip()
        if ds_name not in ds_map:
            ds_map[ds_name] = {
                "name": ds_name,
                "level": str(row.get("level", "DS")) if pd.notna(row.get("level")) else "DS",
                "max_concurrent_projects": int(row.get("max_concurrent_projects", 2)) if pd.notna(row.get("max_concurrent_projects")) else 2,
                "efficiency": float(row.get("efficiency", 1.0)) if pd.notna(row.get("efficiency")) else 1.0,
            }

    data_scientists = list(ds_map.values())
    ds_name_to_id = {ds["name"]: idx + 1 for idx, ds in enumerate(data_scientists)}

    # Extract unique projects and compute date ranges
    project_map: Dict[str, Dict] = {}
    for _, row in df.iterrows():
        project_name = str(row["project"]).strip()
        week_start = pd.to_datetime(row["week_start"]).date()
        allocation = float(row["allocation"])

        if project_name not in project_map:
            project_map[project_name] = {
                "name": project_name,
                "weeks": [],
                "total_fte": 0.0,
            }
        project_map[project_name]["weeks"].append(week_start)
        project_map[project_name]["total_fte"] += allocation

    # Build project objects with FTE requirements
    projects: List[Dict] = []
    project_name_to_id: Dict[str, int] = {}
    for idx, (project_name, project_data) in enumerate(project_map.items()):
        weeks = sorted(set(project_data["weeks"]))
        start_date = weeks[0]
        end_date = weeks[-1] + timedelta(weeks=11)  # Extend 12 weeks from last assignment
        avg_fte = project_data["total_fte"] / len(weeks) if weeks else 1.0

        # Generate FTE requirements for the project duration
        fte_requirements = []
        current = start_date
        while current <= end_date:
            fte_requirements.append({
                "week_start": current.isoformat(),
                "fte": round(avg_fte, 2),
            })
            current += timedelta(weeks=1)

        projects.append({
            "name": project_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "fte_requirements": fte_requirements,
        })
        project_name_to_id[project_name] = idx + 1

    # Build assignments
    assignments: List[Dict] = []
    for _, row in df.iterrows():
        ds_name = str(row["data_scientist"]).strip()
        project_name = str(row["project"]).strip()
        week_start = pd.to_datetime(row["week_start"]).date()
        allocation = float(row["allocation"])

        assignments.append({
            "data_scientist_id": ds_name_to_id[ds_name],
            "project_id": project_name_to_id[project_name],
            "week_start": week_start.isoformat(),
            "allocation": allocation,
        })

    return {
        "config": {"granularity_weeks": 1, "horizon_weeks": 26},
        "data_scientists": data_scientists,
        "projects": projects,
        "assignments": assignments,
    }


def build_seed_data(source: SeedSource = DEFAULT_SEED_SOURCE) -> Dict:
    """Generate seed data from the specified source.
    
    Args:
        source: The seed source to use. Defaults to CSV.
        
    Returns:
        Dictionary containing config, data_scientists, projects, and assignments.
    """
    if source == SeedSource.CSV:
        csv_path = DATA_DIR / "pso_schedule.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV seed file not found: {csv_path}")
        return build_seed_data_from_schedule(csv_path)
    
    elif source == SeedSource.EXCEL:
        excel_path = DATA_DIR / "pso_schedule.xlsx"
        if not excel_path.exists():
            raise FileNotFoundError(f"Excel seed file not found: {excel_path}")
        return build_seed_data_from_schedule(excel_path)
    
    elif source == SeedSource.JSON:
        return build_seed_data_from_json()
    
    else:
        raise ValueError(f"Unknown seed source: {source}")
