"""Named ARTools site and controlled-system configuration."""

from .domain import ControlledSystem, ObserverSite


SRT_SITE = ObserverSite(
    identifier="srt_site",
    name="SRT site",
    latitude_deg=39.49307239,
    longitude_deg=9.24515124,
    height_m=671.6665,
)
"""Observer location of the Auxiliary Telescope at the SRT site."""


AUXILIARY_TELESCOPE = ControlledSystem(
    identifier="auxiliary_telescope",
    name="Auxiliary Telescope",
)
"""The controlled system implemented by the first ARTools application."""


__all__ = ["AUXILIARY_TELESCOPE", "SRT_SITE"]
