"""Bootstrap tests for the installable package."""

import artools


def test_package_exposes_version() -> None:
    """The installed package must expose a version string."""
    assert isinstance(artools.__version__, str)
    assert artools.__version__


def test_installed_package_does_not_expose_legacy_srt_schedule_features() -> None:
    """Current public package scope must exclude legacy SRT/DISCOS scheduling."""
    assert not hasattr(artools, "sched")
    assert not hasattr(artools, "oofscd")
