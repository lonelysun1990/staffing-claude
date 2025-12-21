from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple


def start_of_week(day: date) -> date:
    """Return the Monday of the week for a given date."""
    return day - timedelta(days=day.weekday())


def build_seed_data() -> Dict:
    """Generate deterministic starter data for projects, data scientists, and assignments."""
    today = start_of_week(date.today())

    data_scientists = [
        {
            "name": "Alex Rivera",
            "level": "Senior DS",
            "max_concurrent_projects": 3,
            "efficiency": 1.2,
            "notes": "Team lead",
        },
        {
            "name": "Jamie Patel",
            "level": "Senior DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.1,
        },
        {
            "name": "Taylor Chen",
            "level": "Junior DS",
            "max_concurrent_projects": 1,
            "efficiency": 0.8,
        },
        {
            "name": "Morgan Lee",
            "level": "Mid DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.0,
        },
        {
            "name": "Jordan Kim",
            "level": "Senior DS",
            "max_concurrent_projects": 3,
            "efficiency": 1.25,
        },
        {
            "name": "Casey Brooks",
            "level": "Junior DS",
            "max_concurrent_projects": 1,
            "efficiency": 0.75,
        },
        {
            "name": "Riley Zhao",
            "level": "Mid DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.05,
        },
        {
            "name": "Sam Taylor",
            "level": "Senior DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.15,
        },
        {
            "name": "Avery Morgan",
            "level": "Mid DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.0,
        },
        {
            "name": "Cameron Diaz",
            "level": "Junior DS",
            "max_concurrent_projects": 1,
            "efficiency": 0.85,
        },
        {
            "name": "Drew Wallace",
            "level": "Mid DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.0,
        },
        {
            "name": "Emerson Blake",
            "level": "Senior DS",
            "max_concurrent_projects": 3,
            "efficiency": 1.3,
        },
        {
            "name": "Harper Woods",
            "level": "Mid DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.0,
        },
        {
            "name": "Parker Shaw",
            "level": "Junior DS",
            "max_concurrent_projects": 1,
            "efficiency": 0.9,
        },
        {
            "name": "Reese Porter",
            "level": "Senior DS",
            "max_concurrent_projects": 2,
            "efficiency": 1.2,
        },
    ]

    projects: List[Dict] = []
    assignments: List[Dict] = []

    project_templates: List[Tuple[str, int, float]] = [
        ("Customer 360", 18, 1.5),
        ("Pricing Optimization", 16, 2.0),
        ("Recommendation Engine", 20, 2.5),
        ("Forecasting Revamp", 12, 1.2),
        ("Churn Reduction", 14, 1.0),
        ("NLP Assistant", 10, 1.1),
        ("Anomaly Detection", 8, 0.8),
        ("Experimentation Platform", 22, 2.2),
        ("Data Quality Initiative", 15, 1.4),
        ("Model Governance", 12, 1.0),
    ]

    week_offset = 0
    for index, (name, duration_weeks, base_fte) in enumerate(project_templates):
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

