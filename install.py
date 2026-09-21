"""Cross-platform installer for ARTools.

Typical use::

    python install.py

The installer owns a project-local ``.venv`` so users do not need to create or
activate a virtual environment manually. Runtime users get the web, astronomy,
and satellite extras. Developers can add the development dependencies and an
editable install with ``--dev``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Sequence


MIN_PYTHON = (3, 11)
VENV_DIRNAME = ".venv"
RUNTIME_EXTRAS = ("web", "astronomy", "satellite")
DEV_EXTRA = "dev"


class InstallerError(RuntimeError):
    """Raised for an installation preflight or environment error."""


def build_parser() -> argparse.ArgumentParser:
    """Build the installer command-line parser."""
    parser = argparse.ArgumentParser(
        description="Create an isolated ARTools environment and install the application."
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Remove and recreate the project-local .venv before installing.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install development/test dependencies in editable mode.",
    )
    return parser


def check_python_version(version_info=None) -> None:
    """Require the minimum Python version before touching the environment."""
    version_info = version_info or sys.version_info
    current = (version_info.major, version_info.minor)
    if current < MIN_PYTHON:
        required = ".".join(map(str, MIN_PYTHON))
        detected = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
        raise InstallerError(
            f"ARTools requires Python {required} or newer; detected Python {detected}."
        )


def venv_python(venv_dir: Path, *, os_name: str | None = None) -> Path:
    """Return the Python executable inside a virtual environment."""
    os_name = os_name or os.name
    if os_name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def venv_entry_point(
    venv_dir: Path, name: str, *, os_name: str | None = None
) -> Path:
    """Return an installed console-script path inside a virtual environment."""
    os_name = os_name or os.name
    if os_name == "nt":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def build_install_command(python: Path, *, dev: bool = False) -> list[str]:
    """Return the pip command for a runtime or development installation."""
    extras = list(RUNTIME_EXTRAS)
    if dev:
        extras.append(DEV_EXTRA)
    requirement = f".[{','.join(extras)}]"
    command = [str(python), "-m", "pip", "install"]
    if dev:
        command.append("-e")
    command.append(requirement)
    return command


def _run(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _read_environment_python_version(python: Path, project_root: Path) -> tuple[int, int, int]:
    result = _run(
        [
            python,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
        ],
        cwd=project_root,
        capture_output=True,
    )
    parts = result.stdout.strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise InstallerError(f"Could not determine Python version in {python}.")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def ensure_virtualenv(project_root: Path, *, recreate: bool = False) -> Path:
    """Create or validate the project-local virtual environment."""
    venv_dir = project_root / VENV_DIRNAME

    if recreate and venv_dir.exists():
        print(f"Removing existing environment: {venv_dir}")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        print(f"Creating virtual environment: {venv_dir}")
        try:
            venv.EnvBuilder(with_pip=True).create(venv_dir)
        except Exception as error:  # pragma: no cover - platform failure path
            raise InstallerError(f"Could not create {venv_dir}: {error}") from error

    python = venv_python(venv_dir)
    if not python.is_file():
        raise InstallerError(
            f"{venv_dir} is not a usable ARTools virtual environment. "
            "Run 'python install.py --recreate'."
        )

    try:
        version = _read_environment_python_version(python, project_root)
        _run([python, "-m", "pip", "--version"], cwd=project_root, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as error:
        raise InstallerError(
            f"{venv_dir} is not a usable ARTools virtual environment. "
            "Run 'python install.py --recreate'."
        ) from error

    if version[:2] < MIN_PYTHON:
        detected = ".".join(map(str, version))
        raise InstallerError(
            f"The existing {VENV_DIRNAME} uses Python {detected}, but ARTools "
            f"requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. "
            "Run the installer with a supported Python and --recreate."
        )

    return venv_dir


def launcher_paths(project_root: Path, *, os_name: str | None = None) -> tuple[Path, Path]:
    """Return CLI and GUI launcher paths for the current platform."""
    os_name = os_name or os.name
    if os_name == "nt":
        return project_root / "artools.cmd", project_root / "artools-gui.cmd"
    return project_root / "artools", project_root / "artools-gui"


def _posix_launcher(entry_point: str) -> str:
    return (
        "#!/bin/sh\n"
        'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        f'exec "$SCRIPT_DIR/{VENV_DIRNAME}/bin/{entry_point}" "$@"\n'
    )


def _windows_launcher(entry_point: str) -> str:
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        f'"%~dp0{VENV_DIRNAME}\\Scripts\\{entry_point}.exe" %*\r\n'
    )


def write_launchers(project_root: Path, *, os_name: str | None = None) -> tuple[Path, Path]:
    """Generate local CLI and GUI launchers for the current platform."""
    os_name = os_name or os.name
    cli_path, gui_path = launcher_paths(project_root, os_name=os_name)

    if os_name == "nt":
        cli_path.write_text(_windows_launcher("artools"), encoding="utf-8")
        gui_path.write_text(_windows_launcher("artools-gui"), encoding="utf-8")
    else:
        cli_path.write_text(_posix_launcher("artools"), encoding="utf-8")
        gui_path.write_text(_posix_launcher("artools-gui"), encoding="utf-8")
        cli_path.chmod(0o755)
        gui_path.chmod(0o755)

    return cli_path, gui_path


def run_sanity_checks(project_root: Path, venv_dir: Path) -> str:
    """Verify imports and installed console entry points."""
    python = venv_python(venv_dir)
    result = _run(
        [
            python,
            "-c",
            (
                "import artools, astropy, astroquery, fastapi, pycraf, uvicorn; "
                "print(artools.__version__)"
            ),
        ],
        cwd=project_root,
        capture_output=True,
    )
    version = result.stdout.strip()

    for name in ("artools", "artools-gui"):
        entry_point = venv_entry_point(venv_dir, name)
        if not entry_point.is_file():
            raise InstallerError(f"Installed entry point not found: {entry_point}")
        _run([entry_point, "--help"], cwd=project_root, capture_output=True)

    return version


def _print_usage(project_root: Path, *, os_name: str | None = None) -> None:
    os_name = os_name or os.name
    cli_path, gui_path = launcher_paths(project_root, os_name=os_name)
    print("\nARTools installation completed successfully.")
    if os_name == "nt":
        print("Run the command-line interface with:")
        print(f"  {cli_path.name} --help")
        print("Run the web interface with:")
        print(f"  {gui_path.name}")
    else:
        print("Run the command-line interface with:")
        print(f"  ./{cli_path.name} --help")
        print("Run the web interface with:")
        print(f"  ./{gui_path.name}")
    print(f"Virtual environment: {project_root / VENV_DIRNAME}")


def project_root() -> Path:
    """Return the ARTools source-tree root that contains this installer."""
    return Path(__file__).resolve().parent


def main(argv: Sequence[str] | None = None) -> int:
    """Create/update the local environment, install ARTools, and write launchers."""
    args = build_parser().parse_args(argv)
    root = project_root()

    try:
        check_python_version()
        print(
            f"ARTools installer - Python {sys.version_info.major}."
            f"{sys.version_info.minor}.{sys.version_info.micro} on {sys.platform}"
        )
        venv_dir = ensure_virtualenv(root, recreate=args.recreate)
        python = venv_python(venv_dir)
        command = build_install_command(python, dev=args.dev)
        mode = "development" if args.dev else "runtime"
        print(f"Installing ARTools ({mode}) into {venv_dir} ...")
        _run(command, cwd=root)
        write_launchers(root)
        version = run_sanity_checks(root, venv_dir)
        print(f"Verified ARTools {version}.")
        _print_usage(root)
    except (InstallerError, subprocess.CalledProcessError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
