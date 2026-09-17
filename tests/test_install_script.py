"""Tests for the cross-platform complete-install bootstrap script."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = PROJECT_ROOT / "install.py"


def _load_install_script():
    spec = importlib.util.spec_from_file_location("artools_install_script", INSTALL_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_script_requests_all_project_extras() -> None:
    module = _load_install_script()
    command = module.build_install_command()

    assert command[1:4] == ["-m", "pip", "install"]
    assert command[-2:] == ["-e", ".[web,astronomy,satellite,dev]"]


def test_install_script_uses_project_root_and_active_interpreter(monkeypatch) -> None:
    module = _load_install_script()
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(command, *, cwd, check):
        calls.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main() == 0
    assert len(calls) == 1
    command, cwd, check = calls[0]
    assert command[0] == module.sys.executable
    assert command[-1] == ".[web,astronomy,satellite,dev]"
    assert cwd == PROJECT_ROOT
    assert check is True
