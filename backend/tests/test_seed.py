"""Tests for loading seed data from various sources."""

import pytest

from app.seed import (
    SeedSource,
    build_seed_data,
    build_seed_data_from_json,
    build_seed_data_from_schedule,
    load_data_scientists,
    load_project_templates,
    DATA_DIR,
)


class TestLoadDataScientists:
    """Tests for load_data_scientists function (JSON source)."""

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
    """Tests for load_project_templates function (JSON source)."""

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


class TestBuildSeedDataFromJSON:
    """Tests for build_seed_data with JSON source."""

    def test_returns_dict_with_required_keys(self):
        """Should return a dict with config, data_scientists, projects, assignments."""
        seed_data = build_seed_data(SeedSource.JSON)
        required_keys = {"config", "data_scientists", "projects", "assignments"}

        assert isinstance(seed_data, dict)
        assert required_keys == set(seed_data.keys())

    def test_config_structure(self):
        """Config should have granularity_weeks and horizon_weeks."""
        seed_data = build_seed_data(SeedSource.JSON)
        config = seed_data["config"]

        assert "granularity_weeks" in config
        assert "horizon_weeks" in config
        assert isinstance(config["granularity_weeks"], int)
        assert isinstance(config["horizon_weeks"], int)

    def test_data_scientists_from_json(self):
        """Data scientists in seed data should match JSON file."""
        seed_data = build_seed_data(SeedSource.JSON)
        json_data = load_data_scientists()

        assert seed_data["data_scientists"] == json_data

    def test_projects_generated_from_templates(self):
        """Projects should be generated from templates."""
        seed_data = build_seed_data(SeedSource.JSON)
        templates = load_project_templates()

        assert len(seed_data["projects"]) == len(templates)

        # Each project should have the template name
        project_names = {p["name"] for p in seed_data["projects"]}
        template_names = {t["name"] for t in templates}
        assert project_names == template_names

    def test_project_structure(self):
        """Each project should have required fields."""
        seed_data = build_seed_data(SeedSource.JSON)
        required_fields = {"name", "start_date", "end_date", "fte_requirements"}

        for project in seed_data["projects"]:
            assert required_fields.issubset(project.keys())

    def test_assignments_structure(self):
        """Each assignment should have required fields."""
        seed_data = build_seed_data(SeedSource.JSON)
        required_fields = {"data_scientist_id", "project_id", "week_start", "allocation"}

        for assignment in seed_data["assignments"]:
            assert required_fields.issubset(assignment.keys())


class TestBuildSeedDataFromCSV:
    """Tests for build_seed_data with CSV source (default)."""

    def test_csv_is_default_source(self):
        """CSV should be the default seed source."""
        # Default call should use CSV
        seed_data_default = build_seed_data()
        seed_data_csv = build_seed_data(SeedSource.CSV)
        
        # Both should have same data scientists (by name)
        default_names = {ds["name"] for ds in seed_data_default["data_scientists"]}
        csv_names = {ds["name"] for ds in seed_data_csv["data_scientists"]}
        assert default_names == csv_names

    def test_returns_dict_with_required_keys(self):
        """Should return a dict with config, data_scientists, projects, assignments."""
        seed_data = build_seed_data(SeedSource.CSV)
        required_keys = {"config", "data_scientists", "projects", "assignments"}

        assert isinstance(seed_data, dict)
        assert required_keys == set(seed_data.keys())

    def test_config_structure(self):
        """Config should have granularity_weeks and horizon_weeks."""
        seed_data = build_seed_data(SeedSource.CSV)
        config = seed_data["config"]

        assert "granularity_weeks" in config
        assert "horizon_weeks" in config
        assert isinstance(config["granularity_weeks"], int)
        assert isinstance(config["horizon_weeks"], int)

    def test_data_scientists_extracted(self):
        """Data scientists should be extracted from CSV."""
        seed_data = build_seed_data(SeedSource.CSV)
        
        assert len(seed_data["data_scientists"]) > 0
        for ds in seed_data["data_scientists"]:
            assert "name" in ds
            assert "level" in ds
            assert "efficiency" in ds
            assert "max_concurrent_projects" in ds

    def test_projects_extracted(self):
        """Projects should be extracted from CSV."""
        seed_data = build_seed_data(SeedSource.CSV)
        
        assert len(seed_data["projects"]) > 0
        for project in seed_data["projects"]:
            assert "name" in project
            assert "start_date" in project
            assert "end_date" in project
            assert "fte_requirements" in project

    def test_assignments_extracted(self):
        """Assignments should be extracted from CSV."""
        seed_data = build_seed_data(SeedSource.CSV)
        required_fields = {"data_scientist_id", "project_id", "week_start", "allocation"}

        assert len(seed_data["assignments"]) > 0
        for assignment in seed_data["assignments"]:
            assert required_fields.issubset(assignment.keys())

    def test_assignment_ids_valid(self):
        """Assignment IDs should reference valid data scientists and projects."""
        seed_data = build_seed_data(SeedSource.CSV)
        
        ds_ids = set(range(1, len(seed_data["data_scientists"]) + 1))
        project_ids = set(range(1, len(seed_data["projects"]) + 1))

        for assignment in seed_data["assignments"]:
            assert assignment["data_scientist_id"] in ds_ids
            assert assignment["project_id"] in project_ids


class TestBuildSeedDataFromExcel:
    """Tests for build_seed_data with Excel source."""

    def test_returns_dict_with_required_keys(self):
        """Should return a dict with config, data_scientists, projects, assignments."""
        seed_data = build_seed_data(SeedSource.EXCEL)
        required_keys = {"config", "data_scientists", "projects", "assignments"}

        assert isinstance(seed_data, dict)
        assert required_keys == set(seed_data.keys())

    def test_data_scientists_extracted(self):
        """Data scientists should be extracted from Excel."""
        seed_data = build_seed_data(SeedSource.EXCEL)
        
        assert len(seed_data["data_scientists"]) > 0
        for ds in seed_data["data_scientists"]:
            assert "name" in ds
            assert "efficiency" in ds

    def test_projects_extracted(self):
        """Projects should be extracted from Excel."""
        seed_data = build_seed_data(SeedSource.EXCEL)
        
        assert len(seed_data["projects"]) > 0
        for project in seed_data["projects"]:
            assert "name" in project
            assert "start_date" in project
            assert "end_date" in project

    def test_excel_and_csv_have_same_data(self):
        """Excel and CSV should produce equivalent seed data."""
        csv_data = build_seed_data(SeedSource.CSV)
        excel_data = build_seed_data(SeedSource.EXCEL)

        # Same data scientists by name
        csv_ds_names = {ds["name"] for ds in csv_data["data_scientists"]}
        excel_ds_names = {ds["name"] for ds in excel_data["data_scientists"]}
        assert csv_ds_names == excel_ds_names

        # Same projects by name
        csv_project_names = {p["name"] for p in csv_data["projects"]}
        excel_project_names = {p["name"] for p in excel_data["projects"]}
        assert csv_project_names == excel_project_names
