"""Tests for the cross-platform ARTools installation bootstrap."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = PROJECT_ROOT / "install.py"


def _load_install_script():
    spec = importlib.util.spec_from_file_location("artools_install_script", INSTALL_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_script_runtime_install_uses_runtime_extras() -> None:
    module = _load_install_script()
    python = Path("/tmp/example-python")
    command = module.build_install_command(python)

    assert command == [
        str(python),
        "-m",
        "pip",
        "install",
        ".[web,astronomy,satellite]",
    ]


def test_install_script_dev_install_is_editable_and_adds_dev_extra() -> None:
    module = _load_install_script()
    python = Path("/tmp/example-python")
    command = module.build_install_command(python, dev=True)

    assert command == [
        str(python),
        "-m",
        "pip",
        "install",
        "-e",
        ".[web,astronomy,satellite,dev]",
    ]


def test_python_version_check_rejects_python_310() -> None:
    module = _load_install_script()

    with pytest.raises(module.InstallerError, match="Python 3.11 or newer"):
        module.check_python_version(SimpleNamespace(major=3, minor=10, micro=14))


def test_python_version_check_accepts_python_311() -> None:
    module = _load_install_script()
    module.check_python_version(SimpleNamespace(major=3, minor=11, micro=0))


def test_venv_paths_are_cross_platform() -> None:
    module = _load_install_script()
    root = Path("project") / ".venv"

    assert module.venv_python(root, os_name="posix") == root / "bin" / "python"
    assert module.venv_python(root, os_name="nt") == root / "Scripts" / "python.exe"
    assert module.venv_entry_point(root, "artools", os_name="posix") == root / "bin" / "artools"
    assert module.venv_entry_point(root, "artools", os_name="nt") == root / "Scripts" / "artools.exe"


def test_launcher_paths_are_platform_specific(tmp_path: Path) -> None:
    module = _load_install_script()

    assert module.launcher_paths(tmp_path, os_name="posix") == (
        tmp_path / "artools",
        tmp_path / "artools-gui",
    )
    assert module.launcher_paths(tmp_path, os_name="nt") == (
        tmp_path / "artools.cmd",
        tmp_path / "artools-gui.cmd",
    )


def test_posix_launchers_call_project_venv_without_activation(tmp_path: Path) -> None:
    module = _load_install_script()
    cli, gui = module.write_launchers(tmp_path, os_name="posix")

    assert '.venv/bin/artools" "$@"' in cli.read_text(encoding="utf-8")
    assert '.venv/bin/artools-gui" "$@"' in gui.read_text(encoding="utf-8")
    assert os.access(cli, os.X_OK)
    assert os.access(gui, os.X_OK)


def test_windows_launchers_call_project_venv_without_activation(tmp_path: Path) -> None:
    module = _load_install_script()
    cli, gui = module.write_launchers(tmp_path, os_name="nt")

    assert ".venv\\Scripts\\artools.exe" in cli.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\artools-gui.exe" in gui.read_text(encoding="utf-8")


def test_managed_venv_detection_uses_executable_path_without_resolving(
    tmp_path: Path,
) -> None:
    module = _load_install_script()

    assert module.running_from_managed_venv(
        tmp_path, executable=tmp_path / ".venv" / "bin" / "python"
    )
    assert not module.running_from_managed_venv(
        tmp_path, executable=tmp_path / "system" / "bin" / "python"
    )


def test_find_external_python_prefers_base_executable_outside_managed_venv(
    tmp_path: Path,
) -> None:
    module = _load_install_script()
    base_python = tmp_path / "base-python"
    base_python.write_text("", encoding="utf-8")

    result = module.find_external_python(
        tmp_path,
        base_executable=base_python,
        base_prefix=tmp_path / "missing-prefix",
    )

    assert result == base_python


def test_recreate_restarts_with_external_python_before_deleting_venv(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_install_script()
    base_python = tmp_path / "base-python"
    base_python.write_text("", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(module, "running_from_managed_venv", lambda root: True)
    monkeypatch.setattr(module, "find_external_python", lambda root: base_python)

    class Restarted(Exception):
        pass

    def fake_execv(executable, args):
        calls.append((executable, args))
        raise Restarted

    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Restarted):
        module.restart_for_recreate(tmp_path, ["--recreate", "--dev"])

    assert calls == [
        (
            str(base_python),
            [
                str(base_python),
                str(tmp_path / "install.py"),
                "--recreate",
                "--dev",
            ],
        )
    ]


def test_recreate_fails_safely_if_base_python_cannot_be_found(
    tmp_path: Path,
) -> None:
    module = _load_install_script()
    managed_python = tmp_path / ".venv" / "bin" / "python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("", encoding="utf-8")

    with pytest.raises(module.InstallerError, match="No files were removed"):
        module.find_external_python(
            tmp_path,
            base_executable=managed_python,
            base_prefix=tmp_path / "missing-prefix",
            os_name="posix",
        )


def test_recreate_removes_existing_environment_before_creation(tmp_path: Path, monkeypatch) -> None:
    module = _load_install_script()
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "stale.txt").write_text("stale", encoding="utf-8")
    created: list[Path] = []

    class FakeBuilder:
        def __init__(self, *, with_pip):
            assert with_pip is True

        def create(self, path):
            path = Path(path)
            created.append(path)
            python = module.venv_python(path)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(module, "_read_environment_python_version", lambda *_: (3, 13, 9))
    monkeypatch.setattr(
        module,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    result = module.ensure_virtualenv(tmp_path, recreate=True)

    assert result == venv_dir
    assert created == [venv_dir]
    assert not (venv_dir / "stale.txt").exists()


def test_main_uses_managed_venv_and_generates_launchers(monkeypatch, tmp_path: Path) -> None:
    module = _load_install_script()
    venv_dir = tmp_path / ".venv"
    python = module.venv_python(venv_dir)
    calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(module, "check_python_version", lambda: None)
    monkeypatch.setattr(module, "ensure_virtualenv", lambda root, recreate=False: venv_dir)
    monkeypatch.setattr(module, "venv_python", lambda _: python)
    monkeypatch.setattr(module, "write_launchers", lambda root: (root / "artools", root / "artools-gui"))
    monkeypatch.setattr(module, "run_sanity_checks", lambda root, env: "0.1.0")
    monkeypatch.setattr(module, "_print_usage", lambda root: None)
    monkeypatch.setattr(module, "project_root", lambda: tmp_path)

    def fake_run(command, *, cwd, capture_output=False):
        calls.append(([str(part) for part in command], cwd))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module, "_run", fake_run)

    assert module.main([]) == 0
    assert calls == [
        (
            [
                str(python),
                "-m",
                "pip",
                "install",
                ".[web,astronomy,satellite]",
            ],
            tmp_path,
        )
    ]


def test_existing_venv_with_old_python_is_rejected(tmp_path: Path, monkeypatch) -> None:
    module = _load_install_script()
    venv_dir = tmp_path / ".venv"
    python = module.venv_python(venv_dir)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "_read_environment_python_version", lambda *_: (3, 10, 14))
    monkeypatch.setattr(
        module,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )

    with pytest.raises(module.InstallerError, match="uses Python 3.10.14"):
        module.ensure_virtualenv(tmp_path)
