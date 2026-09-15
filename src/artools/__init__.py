"""ARTools package.

The new implementation is intentionally minimal at roadmap Step 0. Trajectory
calculation will be introduced incrementally in later roadmap steps.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("artools")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
