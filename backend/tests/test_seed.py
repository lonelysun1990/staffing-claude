"""Tests for loading seed data from JSON files."""

import pytest

from app.seed import load_data_scientists, load_project_templates, build_seed_data


class TestLoadDataScientists:
    """Tests for load_data_scientists function."""

    def test_loads_successfully(self):
        """Should load data scientists from JSON file."""
        data_scientists = load_data_scientists()
        assert isinstance(data_scientists, list)
        assert len(data_scientists) > 0

    def test_has_required_fields(self):
        """Each data scientist should have required fields."""
        data_scientists = load_data_scientists()
        required_fields = {"name", "level", "max_concurrent_projects", "efficiency"}

        for ds in data_scientists:
            assert required_fields.issubset(ds.keys()), f"Missing fields in {ds}"

    def test_field_types(self):
        """Fields should have correct types."""
        data_scientists = load_data_scientists()

        for ds in data_scientists:
            assert isinstance(ds["name"], str)
            assert isinstance(ds["level"], str)
            assert isinstance(ds["max_concurrent_projects"], int)
            assert isinstance(ds["efficiency"], (int, float))

    def test_valid_levels(self):
        """Level should be one of the expected values."""
        data_scientists = load_data_scientists()
        valid_levels = {"Junior DS", "Mid DS", "Senior DS"}

        for ds in data_scientists:
            assert ds["level"] in valid_levels, f"Invalid level: {ds['level']}"

    def test_positive_values(self):
        """Numeric fields should be positive."""
        data_scientists = load_data_scientists()

        for ds in data_scientists:
            assert ds["max_concurrent_projects"] > 0
            assert ds["efficiency"] > 0


class TestLoadProjectTemplates:
    """Tests for load_project_templates function."""

    def test_loads_successfully(self):
        """Should load project templates from JSON file."""
        templates = load_project_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0

    def test_has_required_fields(self):
        """Each template should have required fields."""
        templates = load_project_templates()
        required_fields = {"name", "duration_weeks", "base_fte"}

        for template in templates:
            assert required_fields.issubset(template.keys()), f"Missing fields in {template}"

    def test_field_types(self):
        """Fields should have correct types."""
        templates = load_project_templates()

        for template in templates:
            assert isinstance(template["name"], str)
            assert isinstance(template["duration_weeks"], int)
            assert isinstance(template["base_fte"], (int, float))

    def test_positive_values(self):
        """Numeric fields should be positive."""
        templates = load_project_templates()

        for template in templates:
            assert template["duration_weeks"] > 0
            assert template["base_fte"] > 0


class TestBuildSeedData:
    """Tests for build_seed_data function."""

    def test_returns_dict_with_required_keys(self):
        """Should return a dict with config, data_scientists, projects, assignments."""
        seed_data = build_seed_data()
        required_keys = {"config", "data_scientists", "projects", "assignments"}

        assert isinstance(seed_data, dict)
        assert required_keys == set(seed_data.keys())

    def test_config_structure(self):
        """Config should have granularity_weeks and horizon_weeks."""
        seed_data = build_seed_data()
        config = seed_data["config"]

        assert "granularity_weeks" in config
        assert "horizon_weeks" in config
        assert isinstance(config["granularity_weeks"], int)
        assert isinstance(config["horizon_weeks"], int)

    def test_data_scientists_from_json(self):
        """Data scientists in seed data should match JSON file."""
        seed_data = build_seed_data()
        json_data = load_data_scientists()

        assert seed_data["data_scientists"] == json_data

    def test_projects_generated_from_templates(self):
        """Projects should be generated from templates."""
        seed_data = build_seed_data()
        templates = load_project_templates()

        assert len(seed_data["projects"]) == len(templates)

        # Each project should have the template name
        project_names = {p["name"] for p in seed_data["projects"]}
        template_names = {t["name"] for t in templates}
        assert project_names == template_names

    def test_project_structure(self):
        """Each project should have required fields."""
        seed_data = build_seed_data()
        required_fields = {"name", "start_date", "end_date", "fte_requirements"}

        for project in seed_data["projects"]:
            assert required_fields.issubset(project.keys())

    def test_assignments_structure(self):
        """Each assignment should have required fields."""
        seed_data = build_seed_data()
        required_fields = {"data_scientist_id", "project_id", "week_start", "allocation"}

        for assignment in seed_data["assignments"]:
            assert required_fields.issubset(assignment.keys())

