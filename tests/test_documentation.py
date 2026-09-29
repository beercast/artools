from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_is_the_single_current_markdown_documentation_entry_point() -> None:
    assert (ROOT / "README.md").is_file()
    assert not (ROOT / "docs").exists()


def test_readme_contains_functional_cli_and_development_sections() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in (
        "## Functional overview",
        "### Astronomical source",
        "### Solar System body",
        "### Satellite",
        "## Command-line interface",
        "## Development",
        "### Development installation",
        "### Checking compatibility with the legacy version",
    ):
        assert expected in readme


def test_readme_covers_primary_change_points_and_satellite_catalog_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in (
        "tracking.py",
        "cross_scan.py",
        "raster_map.py",
        "AuxiliaryTelescopeTrajectoryWriter",
        "TleCatalogStore",
        "Download fresh TLE",
        "Upload catalog file",
        "Paste TLE manually",
        "--download-tle --satellite NAME",
        "--tle-file PATH --satellite NAME",
    ):
        assert expected in readme
