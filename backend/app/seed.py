from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def build_seed_data() -> Dict:
    """Generate deterministic starter data for projects, data scientists, and assignments."""
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
