"""Observing-site catalog adapters used by ARTools."""

from __future__ import annotations

from typing import Protocol

from .domain import ObserverSite


class SiteCatalogError(RuntimeError):
    """Raised when an external observing-site catalog cannot be used."""


class ObservatoryCatalog(Protocol):
    """List and resolve named observing sites."""

    def names(self) -> tuple[str, ...]:
        """Return the names available in the catalog."""
        ...

    def resolve(self, name: str) -> ObserverSite:
        """Resolve one catalog name to explicit geodetic coordinates."""
        ...


class AstropyObservatoryCatalog:
    """Use Astropy's cached site registry as the optional global site catalog."""

    _SRT_ALIASES = {
        "srt",
        "srt site",
        "sardinia radio telescope",
        "sardinia radio telescope (srt)",
    }

    def names(self) -> tuple[str, ...]:
        try:
            from astropy.coordinates import EarthLocation
        except ImportError as error:
            raise SiteCatalogError(
                "The Astropy observing-site catalog requires the 'astronomy' "
                "optional dependencies"
            ) from error

        try:
            names = EarthLocation.get_site_names()
        except Exception as error:
            raise SiteCatalogError("Could not load the Astropy observing-site catalog") from error

        unique: dict[str, str] = {}
        for raw_name in names:
            name = str(raw_name).strip()
            if not name or name.casefold() in self._SRT_ALIASES:
                continue
            unique.setdefault(name.casefold(), name)
        return tuple(sorted(unique.values(), key=str.casefold))

    def resolve(self, name: str) -> ObserverSite:
        if not isinstance(name, str):
            raise TypeError("Observatory name must be a string")
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Observatory name must not be empty")

        try:
            from astropy import units as u
            from astropy.coordinates import EarthLocation
        except ImportError as error:
            raise SiteCatalogError(
                "The Astropy observing-site catalog requires the 'astronomy' "
                "optional dependencies"
            ) from error

        try:
            location = EarthLocation.of_site(cleaned)
            longitude, latitude, height = location.to_geodetic()
        except Exception as error:
            raise SiteCatalogError(f"Could not resolve observing site: {cleaned}") from error

        display_name = str(getattr(location.info, "name", "") or cleaned).strip()
        identifier = "astropy_" + _identifier_component(cleaned)
        return ObserverSite(
            identifier=identifier,
            name=display_name,
            latitude_deg=float(latitude.to_value(u.deg)),
            longitude_deg=float(longitude.to_value(u.deg)),
            height_m=float(height.to_value(u.m)),
        )


def _identifier_component(value: str) -> str:
    output: list[str] = []
    separator_pending = False
    for char in value.strip().casefold():
        if char.isascii() and char.isalnum():
            if separator_pending and output:
                output.append("_")
            output.append(char)
            separator_pending = False
        else:
            separator_pending = True
    return "".join(output).strip("_") or "site"


__all__ = ["AstropyObservatoryCatalog", "ObservatoryCatalog", "SiteCatalogError"]
