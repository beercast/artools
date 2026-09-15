"""Bootstrap tests for the installable package."""

import artools


def test_package_exposes_version() -> None:
    """The installed package must expose a version string."""
    assert isinstance(artools.__version__, str)
    assert artools.__version__
