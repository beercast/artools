from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docs_directory_contains_only_current_markdown_documents() -> None:
    markdown_files = {path.name for path in (ROOT / "docs").glob("*.md")}
    assert markdown_files == {"user.md", "developer.md"}


def test_readme_links_to_user_and_developer_documentation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[User documentation](docs/user.md)" in readme
    assert "[Developer documentation](docs/developer.md)" in readme


def test_readme_stops_before_detailed_installation_and_cli_reference() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "### Installation details" not in readme
    assert "## Command-line interface" not in readme


def test_developer_documentation_covers_primary_change_points() -> None:
    developer = (ROOT / "docs" / "developer.md").read_text(encoding="utf-8")
    for expected in (
        "generate_tracking_trajectory()",
        "generate_cross_scan_trajectory()",
        "generate_raster_map_trajectory()",
        "AuxiliaryTelescopeTrajectoryWriter",
        "Legacy notebook mapping",
        "SimbadSourceCatalog",
        "SourceFavoritesStore",
    ):
        assert expected in developer
