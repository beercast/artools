"""Release metadata checks for the first Auxiliary Telescope release."""

from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)


def test_release_version_and_python_floor_are_explicit() -> None:
    project = _metadata()["project"]
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.11"


def test_optional_dependency_groups_remain_separate() -> None:
    extras = _metadata()["project"]["optional-dependencies"]
    assert set(extras) == {"astronomy", "satellite", "web", "dev"}
    assert any(requirement.startswith("fastapi>=") for requirement in extras["web"])
    assert any(requirement.startswith("astropy>=") for requirement in extras["astronomy"])
    assert any(requirement.startswith("pycraf>=") for requirement in extras["satellite"])
    assert any(requirement.startswith("httpx2>=") for requirement in extras["dev"])
