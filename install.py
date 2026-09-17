"""Install the complete ARTools development environment.

Run from any directory with::

    python install.py

The dependency definitions remain in ``pyproject.toml``.  This script is only a
cross-platform bootstrap shortcut for installing every project extra in editable
mode with the Python interpreter that launched the script.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


EXTRAS = ("web", "astronomy", "satellite", "dev")


def build_install_command() -> list[str]:
    """Return the pip command used for a complete editable installation."""
    extras = ",".join(EXTRAS)
    return [sys.executable, "-m", "pip", "install", "-e", f".[{extras}]"]


def main() -> int:
    """Install ARTools with all runtime and development extras."""
    project_root = Path(__file__).resolve().parent
    command = build_install_command()
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"ARTools complete installation: {printable}")
    subprocess.run(command, cwd=project_root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
