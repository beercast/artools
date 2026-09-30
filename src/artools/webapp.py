"""Local FastAPI web adapter for ARTools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
from typing import Callable, Mapping

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from .application import (
    ApplicationError,
    TrajectoryApplicationService,
    TrajectoryGenerationRequest,
)
from .astronomical import (
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    AstronomyDependencyError,
    SimbadSourceCatalog,
    SimbadSourceCatalogError,
)
from .auxiliary_telescope import AuxiliaryTelescopeTrajectoryWriter
from .domain import (
    AtmosphericParameters,
    AstronomicalSourceTarget,
    TargetFamily,
    TrajectoryMode,
    TrajectoryRequestParameters,
)
from .parsing import InputParseError, parse_utc_datetime
from .preferences import PreferencesError, SourceFavoritesStore
from .satellite import (
    SatelliteDependencyError,
    SatelliteNotFoundError,
    SatelliteRefractionParameters,
    SatelliteTarget,
    TleCatalogError,
    TleFormatError,
)
from .solar_system import (
    SolarSystemBodyTarget,
    SolarSystemDependencyError,
    UnsupportedSolarSystemBodyError,
)
from .web_ui import render_dynamic_fields, render_index


SIMBAD_SUGGESTION_LIMIT = 20


class WebInputError(ValueError):
    """Raised when submitted web form data is invalid."""


@dataclass(frozen=True, slots=True)
class GeneratedDownload:
    """Serialized trajectory and response metadata returned by a web generation."""

    content: bytes
    filename: str
    point_count: int


def create_app(
    application: TrajectoryApplicationService | None = None,
    *,
    writer: AuxiliaryTelescopeTrajectoryWriter | None = None,
    simbad_catalog: SimbadSourceCatalog | None = None,
    favorites: SourceFavoritesStore | None = None,
    open_directory: Callable[[Path], None] | None = None,
) -> FastAPI:
    """Create the local ARTools FastAPI application.

    The application service remains synchronous. The HTTP generation route is
    async only for request parsing; request construction, optional catalog
    lookup, trajectory calculation, and serialization run through Starlette's
    worker-thread helper so they never execute on the ASGI event loop.
    """
    service = application or TrajectoryApplicationService()
    trajectory_writer = writer or AuxiliaryTelescopeTrajectoryWriter()
    source_catalog = simbad_catalog or SimbadSourceCatalog()
    favorites_store = favorites or SourceFavoritesStore()
    directory_opener = open_directory or _open_directory
    app = FastAPI(title="ARTools", docs_url=None, redoc_url=None)
    assets = Path(__file__).with_name("web_assets")
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index())

    @app.get("/ui/fields", response_class=HTMLResponse)
    def fields(target_family: str = "astronomical", mode: str = "track") -> HTMLResponse:
        return HTMLResponse(render_dynamic_fields(target_family, mode))

    @app.get("/api/simbad/suggestions")
    async def simbad_suggestions(q: str = "") -> JSONResponse:
        query = q.strip()
        if len(query) < 2:
            return JSONResponse(
                {
                    "suggestions": [],
                    "limit": SIMBAD_SUGGESTION_LIMIT,
                    "limit_reached": False,
                }
            )
        try:
            matches = await run_in_threadpool(
                source_catalog.search, query, SIMBAD_SUGGESTION_LIMIT
            )
            favorite_names = {_favorite_key(name) for name in favorites_store.list()}
        except (AstronomyDependencyError, SimbadSourceCatalogError) as error:
            return JSONResponse({"detail": str(error)}, status_code=502)
        except PreferencesError as error:
            return JSONResponse({"detail": str(error)}, status_code=500)

        return JSONResponse(
            {
                "suggestions": [
                    {
                        "name": match.matched_id,
                        "main_id": match.main_id,
                        "favorite": _favorite_key(match.main_id) in favorite_names,
                    }
                    for match in matches
                ],
                "limit": SIMBAD_SUGGESTION_LIMIT,
                "limit_reached": len(matches) >= SIMBAD_SUGGESTION_LIMIT,
            }
        )

    @app.get("/api/simbad/favorites")
    def simbad_favorites() -> JSONResponse:
        try:
            return JSONResponse({"favorites": list(favorites_store.list())})
        except PreferencesError as error:
            return JSONResponse({"detail": str(error)}, status_code=500)

    @app.post("/api/simbad/favorites")
    async def add_simbad_favorite(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"detail": "Invalid favorite request"}, status_code=400)
        name = str(payload.get("name", "")).strip() if isinstance(payload, dict) else ""
        if not name:
            return JSONResponse({"detail": "SIMBAD source name is required"}, status_code=400)
        try:
            verified = await run_in_threadpool(source_catalog.verify, name)
            updated = favorites_store.add(verified.main_id)
        except AstronomicalSourceNotFoundError as error:
            return JSONResponse({"detail": str(error)}, status_code=404)
        except (AstronomyDependencyError, SimbadSourceCatalogError) as error:
            return JSONResponse({"detail": str(error)}, status_code=502)
        except (PreferencesError, ValueError) as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        return JSONResponse(
            {
                "favorite": verified.main_id,
                "favorites": list(updated),
            }
        )

    @app.delete("/api/simbad/favorites")
    def remove_simbad_favorite(name: str = "") -> JSONResponse:
        if not name.strip():
            return JSONResponse({"detail": "SIMBAD source name is required"}, status_code=400)
        try:
            updated = favorites_store.remove(name)
        except (PreferencesError, ValueError) as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        return JSONResponse({"favorites": list(updated)})

    @app.get("/api/tle/downloaded")
    def downloaded_tle_catalog() -> JSONResponse:
        try:
            records = service.downloaded_tle_catalog()
        except _USER_FACING_ERRORS as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        if not records:
            return JSONResponse({"available": False, "satellites": []})
        return JSONResponse(
            {
                "available": True,
                "catalog_id": "norad_tle.txt",
                "filename": "norad_tle.txt",
                "count": len(records),
                "satellites": [record.name for record in records],
            }
        )

    @app.post("/api/tle/download")
    async def download_tle_catalog() -> JSONResponse:
        try:
            records = await run_in_threadpool(service.refresh_downloaded_tle_catalog)
        except _USER_FACING_ERRORS as error:
            return JSONResponse({"detail": str(error)}, status_code=502)
        return JSONResponse(
            {
                "available": True,
                "catalog_id": "norad_tle.txt",
                "filename": "norad_tle.txt",
                "count": len(records),
                "satellites": [record.name for record in records],
            }
        )

    @app.post("/api/tle/upload")
    async def upload_tle_catalog(request: Request) -> JSONResponse:
        form = await request.form()
        upload = form.get("catalog_file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            return JSONResponse({"detail": "Choose a TLE catalog file"}, status_code=400)
        try:
            text = (await upload.read()).decode("ascii")
        except UnicodeDecodeError:
            return JSONResponse(
                {"detail": "Uploaded TLE catalog must contain ASCII text"},
                status_code=400,
            )
        try:
            catalog_id, records = await run_in_threadpool(
                service.import_tle_catalog, upload.filename, text
            )
        except _USER_FACING_ERRORS as error:
            return JSONResponse({"detail": str(error)}, status_code=400)
        return JSONResponse(
            {
                "available": True,
                "catalog_id": catalog_id,
                "filename": catalog_id,
                "count": len(records),
                "satellites": [record.name for record in records],
            }
        )

    @app.post("/api/tle/open-folder")
    async def open_tle_folder() -> JSONResponse:
        try:
            service.tle_catalog_directory.mkdir(parents=True, exist_ok=True)
            await run_in_threadpool(directory_opener, service.tle_catalog_directory)
        except OSError as error:
            return JSONResponse(
                {"detail": f"Could not open TLE folder: {error}"}, status_code=500
            )
        return JSONResponse({"opened": True})

    @app.post("/generate")
    async def generate(request: Request) -> Response:
        form = await request.form()
        values = {key: str(value) for key, value in form.multi_items() if key != "tle_file"}
        uploaded_tle_text: str | None = None
        upload = form.get("tle_file")
        if isinstance(upload, UploadFile) and upload.filename:
            try:
                uploaded_tle_text = (await upload.read()).decode("ascii")
            except UnicodeDecodeError:
                return JSONResponse(
                    {"detail": "Uploaded TLE file must contain ASCII text"},
                    status_code=400,
                )

        try:
            result = await run_in_threadpool(
                _generate_download,
                values,
                uploaded_tle_text,
                service,
                trajectory_writer,
            )
        except _USER_FACING_ERRORS as error:
            return JSONResponse({"detail": str(error)}, status_code=400)

        headers = {
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-ARTools-Point-Count": str(result.point_count),
            "Cache-Control": "no-store",
        }
        return Response(
            content=result.content,
            media_type="text/plain; charset=us-ascii",
            headers=headers,
        )

    return app


def _generate_download(
    values: Mapping[str, str],
    uploaded_tle_text: str | None,
    application: TrajectoryApplicationService,
    writer: AuxiliaryTelescopeTrajectoryWriter,
) -> GeneratedDownload:
    request = request_from_web_form(values, uploaded_tle_text, application)
    trajectory = application.generate_trajectory(request)
    serialized = writer.serialize(trajectory).encode("ascii")
    requested_filename = values.get("output_name", "").strip()
    filename = (
        _download_filename(requested_filename)
        if requested_filename
        else _default_download_filename(request)
    )
    return GeneratedDownload(
        content=serialized,
        filename=filename,
        point_count=len(trajectory),
    )


def request_from_web_form(
    values: Mapping[str, str],
    uploaded_tle_text: str | None,
    application: TrajectoryApplicationService,
) -> TrajectoryGenerationRequest:
    """Convert web form values into the shared validated application request."""
    controlled_system = _value(values, "controlled_system", "auxiliary_telescope")
    if controlled_system != "auxiliary_telescope":
        raise WebInputError("Only the Auxiliary Telescope is currently supported")

    family = _target_family(_required(values, "target_family", "Target family"))
    mode = _trajectory_mode(_required(values, "mode", "Trajectory mode"))
    parameters = TrajectoryRequestParameters(
        target_family=family,
        trajectory_mode=mode,
        start_time=parse_utc_datetime(_web_start_time(values)),
        sample_interval_s=_float(values, "dt", "Sample interval"),
        point_count=_int(values, "points", "Requested points"),
    )
    half_span = None if mode is TrajectoryMode.TRACKING else _float(
        values, "half_span_deg", "Half span", default=2.0
    )

    if family is TargetFamily.ASTRONOMICAL_SOURCE:
        source_name = values.get("source_canonical", "").strip() or _required(
            values, "source", "SIMBAD source name"
        )
        return TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget(source_name),
            parameters=parameters,
            half_span_deg=half_span,
            atmosphere=_atmosphere(values),
        )

    if family is TargetFamily.SOLAR_SYSTEM_BODY:
        return TrajectoryGenerationRequest(
            target=SolarSystemBodyTarget.from_name(
                _required(values, "body", "Solar System body")
            ),
            parameters=parameters,
            half_span_deg=half_span,
            atmosphere=_atmosphere(values),
        )

    target = _satellite_target(values, uploaded_tle_text, application)
    return TrajectoryGenerationRequest(
        target=target,
        parameters=parameters,
        half_span_deg=half_span,
        satellite_refraction=SatelliteRefractionParameters(
            enabled=_checkbox(values, "refraction"),
            frequency_ghz=_float(
                values,
                "refraction_frequency_ghz",
                "Refraction frequency",
                default=22.0,
            ),
            observer_altitude_m=_float(
                values,
                "refraction_altitude_m",
                "Refraction observer altitude",
                default=650.0,
            ),
        ),
    )



def _favorite_key(name: str) -> str:
    value = name.strip()
    if value.casefold().startswith("name "):
        value = value[5:].lstrip()
    return value.casefold()


def _web_start_time(values: Mapping[str, str]) -> str:
    """Return the web start time as an explicit UTC ISO-8601 string.

    The browser UI submits separate native date/time controls. The legacy
    single ``start`` field remains accepted for backwards compatibility with
    existing callers and tests.
    """
    start_date = _value(values, "start_date").strip()
    start_time = _value(values, "start_time").strip()
    if start_date or start_time:
        if not start_date or not start_time:
            raise WebInputError("Start date and start time must both be provided")
        return f"{start_date}T{start_time}Z"
    return _required(values, "start", "Start time")

def _satellite_target(
    values: Mapping[str, str],
    uploaded_tle_text: str | None,
    application: TrajectoryApplicationService,
) -> SatelliteTarget:
    source = _value(values, "tle_source").strip()

    if source == "paste":
        return application.satellite_target_from_tle_text(
            _required(values, "tle_text", "Named TLE")
        )

    if source in {"download", "upload"}:
        satellite_name = _required(values, "satellite_name", "Satellite")
        if source == "download":
            return application.satellite_target_from_downloaded_catalog(satellite_name)
        catalog_id = _required(values, "tle_catalog_id", "Uploaded TLE catalog")
        return application.satellite_target_from_stored_catalog(
            catalog_id, satellite_name
        )

    # Backwards-compatible handling for older callers/tests that submit the
    # pre-catalog satellite form fields directly.
    pasted = _value(values, "tle_text").strip()
    catalog_name = _value(values, "catalog_name").strip()
    choices = [
        bool(pasted),
        bool(uploaded_tle_text and uploaded_tle_text.strip()),
        bool(catalog_name),
    ]
    if sum(choices) != 1:
        raise WebInputError(
            "Choose one TLE source: downloaded catalog, uploaded catalog, or pasted TLE"
        )
    if pasted:
        return application.satellite_target_from_tle_text(pasted)
    if uploaded_tle_text and uploaded_tle_text.strip():
        return application.satellite_target_from_tle_text(uploaded_tle_text)
    return application.satellite_target_from_catalog(catalog_name)


def _atmosphere(values: Mapping[str, str]) -> AtmosphericParameters:
    return AtmosphericParameters(
        pressure_hpa=_float(values, "pressure_hpa", "Pressure", default=0.0),
        temperature_c=_float(values, "temperature_c", "Temperature", default=0.0),
        relative_humidity=_float(
            values, "relative_humidity", "Relative humidity", default=0.0
        ),
        wavelength_m=_float(values, "wavelength_m", "Wavelength", default=0.013627),
    )


def _target_family(value: str) -> TargetFamily:
    mapping = {
        "astronomical": TargetFamily.ASTRONOMICAL_SOURCE,
        "solar-system": TargetFamily.SOLAR_SYSTEM_BODY,
        "satellite": TargetFamily.SATELLITE,
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise WebInputError(f"Unsupported target family: {value!r}") from error


def _trajectory_mode(value: str) -> TrajectoryMode:
    mapping = {
        "track": TrajectoryMode.TRACKING,
        "cross-scan": TrajectoryMode.CROSS_SCAN,
        "map": TrajectoryMode.RASTER_MAP,
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise WebInputError(f"Unsupported trajectory mode: {value!r}") from error


def _default_download_filename(request: TrajectoryGenerationRequest) -> str:
    """Build the default browser filename from target name and start epoch."""
    target = request.target
    if isinstance(target, AstronomicalSourceTarget):
        target_name = target.name
    elif isinstance(target, SolarSystemBodyTarget):
        target_name = target.body.value
    else:
        target_name = target.tle.name

    safe_name = _filename_component(target_name) or "target"
    epoch = request.parameters.start_time.strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_name}_{epoch}.txt"


def _filename_component(value: str) -> str:
    """Return a compact ASCII-safe target name for an automatic filename."""
    output: list[str] = []
    underscore_pending = False
    for char in value.strip():
        if char.isascii() and char.isalnum():
            if underscore_pending and output:
                output.append("_")
            output.append(char)
            underscore_pending = False
        elif char in {"-", "_"}:
            if underscore_pending and output:
                output.append("_")
            output.append(char)
            underscore_pending = False
        elif char.isspace():
            underscore_pending = True
        # Other punctuation is omitted. This turns e.g. W3(OH) into W3OH.
    return "".join(output).strip("_-")


def _download_filename(value: str) -> str:
    filename = value.strip() or "trajectory.txt"
    if filename in {".", ".."} or Path(filename).name != filename:
        raise WebInputError("Download filename must be a filename, not a filesystem path")
    if any(char in filename for char in ("/", "\\", "\r", "\n", '"')):
        raise WebInputError("Download filename contains unsupported characters")
    try:
        filename.encode("ascii")
    except UnicodeEncodeError as error:
        raise WebInputError("Download filename must use ASCII characters") from error
    return filename


def _required(values: Mapping[str, str], key: str, label: str) -> str:
    value = _value(values, key).strip()
    if not value:
        raise WebInputError(f"{label} is required")
    return value


def _value(values: Mapping[str, str], key: str, default: str = "") -> str:
    value = values.get(key, default)
    return value if isinstance(value, str) else str(value)


def _float(
    values: Mapping[str, str], key: str, label: str, *, default: float | None = None
) -> float:
    raw = _value(values, key).strip()
    if not raw and default is not None:
        return default
    if not raw:
        raise WebInputError(f"{label} is required")
    try:
        return float(raw)
    except ValueError as error:
        raise WebInputError(f"{label} must be a number") from error


def _int(values: Mapping[str, str], key: str, label: str) -> int:
    raw = _value(values, key).strip()
    if not raw:
        raise WebInputError(f"{label} is required")
    try:
        return int(raw)
    except ValueError as error:
        raise WebInputError(f"{label} must be an integer") from error


def _checkbox(values: Mapping[str, str], key: str) -> bool:
    return _value(values, key).strip().casefold() in {"1", "true", "on", "yes"}


def _open_directory(path: Path) -> None:
    """Open a local directory in the platform file manager."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    try:
        subprocess.Popen(  # noqa: S603 - fixed local file-manager command
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise OSError(f"No file manager command is available for {path}") from error


_USER_FACING_ERRORS = (
    ApplicationError,
    AstronomyDependencyError,
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    SimbadSourceCatalogError,
    SolarSystemDependencyError,
    UnsupportedSolarSystemBodyError,
    SatelliteDependencyError,
    SatelliteNotFoundError,
    TleCatalogError,
    TleFormatError,
    InputParseError,
    WebInputError,
    TypeError,
    ValueError,
)


__all__ = [
    "GeneratedDownload",
    "WebInputError",
    "create_app",
    "request_from_web_form",
]
