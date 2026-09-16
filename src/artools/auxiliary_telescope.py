"""Auxiliary Telescope trajectory serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .domain import Trajectory


def format_legacy_dms(angle_deg: float) -> str:
    """Format degrees using the exact legacy ``deg_min_sec`` behavior.

    Fractional arcseconds are truncated. For compatibility with ``savetrack``,
    a negative angle with absolute value below one degree loses its sign because
    the legacy formatter applies the sign only to the integer degree component.
    """
    minutes, seconds = divmod(abs(angle_deg) * 3600, 60)
    degrees, minutes = divmod(minutes, 60)
    if angle_deg < 0:
        degrees = -degrees
    degrees, minutes, seconds = int(degrees), int(minutes), int(seconds)
    return f"{degrees:03d}:{minutes:02d}:{seconds:02d}"


def format_auxiliary_timestamp(timestamp: datetime) -> str:
    """Format a UTC timestamp in the Auxiliary Telescope legacy representation."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Trajectory timestamps must be timezone-aware")
    if timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("Trajectory timestamps must be expressed in UTC")

    timestamp = timestamp.astimezone(timezone.utc)
    milliseconds = timestamp.microsecond // 1000
    return timestamp.strftime("%Y/%m/%d %H:%M:%S") + f".{milliseconds:03d}"


class AuxiliaryTelescopeTrajectoryWriter:
    """Serialize trajectories for the Auxiliary Telescope control software."""

    def serialize(self, trajectory: Trajectory) -> str:
        """Return the complete legacy-compatible trajectory file content."""
        return "".join(
            f"{format_auxiliary_timestamp(point.timestamp)}, "
            f"{format_legacy_dms(point.azimuth_deg)}, "
            f"{format_legacy_dms(point.elevation_deg)}\n"
            for point in trajectory
        )

    def write(self, path: str | Path, trajectory: Trajectory) -> Path:
        """Write a trajectory file and return its path."""
        output_path = Path(path)
        output_path.write_text(self.serialize(trajectory), encoding="ascii", newline="\n")
        return output_path


__all__ = [
    "AuxiliaryTelescopeTrajectoryWriter",
    "format_auxiliary_timestamp",
    "format_legacy_dms",
]
