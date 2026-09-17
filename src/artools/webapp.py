"""Local FastAPI web adapter for ARTools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from .application import ApplicationError, TrajectoryApplicationService, TrajectoryGenerationRequest
from .astronomical import (
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
    AstronomyDependencyError,
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
from .satellite import (
    SatelliteDependencyError,
    SatelliteNotFoundError,
    SatelliteRefractionParameters,
    SatelliteTarget,
    TleCatalogError,
    TleData,
    TleFormatError,
)
from .solar_system import (
    SolarSystemBodyTarget,
    SolarSystemDependencyError,
    UnsupportedSolarSystemBodyError,
)
from .web_ui import render_dynamic_fields, render_index


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
) -> FastAPI:
    """Create the local ARTools FastAPI application.

    The application service remains synchronous. The HTTP generation route is
    async only for request parsing; request construction, optional catalog
    lookup, trajectory calculation, and serialization run through Starlette's
    worker-thread helper so they never execute on the ASGI event loop.
    """
    service = application or TrajectoryApplicationService()
    trajectory_writer = writer or AuxiliaryTelescopeTrajectoryWriter()
    app = FastAPI(title="ARTools", docs_url=None, redoc_url=None)
    assets = Path(__file__).with_name("web_assets")
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index())

    @app.get("/ui/fields", response_class=HTMLResponse)
    def fields(target_family: str = "astronomical", mode: str = "track") -> HTMLResponse:
        return HTMLResponse(render_dynamic_fields(target_family, mode))

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
    return GeneratedDownload(
        content=serialized,
        filename=_download_filename(values.get("output_name", "trajectory.txt")),
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
        return TrajectoryGenerationRequest(
            target=AstronomicalSourceTarget(_required(values, "source", "SIMBAD source name")),
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
    pasted = _value(values, "tle_text").strip()
    catalog_name = _value(values, "catalog_name").strip()
    choices = [bool(pasted), bool(uploaded_tle_text and uploaded_tle_text.strip()), bool(catalog_name)]
    if sum(choices) != 1:
        raise WebInputError(
            "Provide exactly one satellite source: pasted TLE, uploaded TLE file, "
            "or CelesTrak name"
        )
    if pasted:
        return SatelliteTarget(TleData.from_three_line_string(pasted))
    if uploaded_tle_text and uploaded_tle_text.strip():
        return SatelliteTarget(TleData.from_three_line_string(uploaded_tle_text))
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


_USER_FACING_ERRORS = (
    ApplicationError,
    AstronomyDependencyError,
    AstronomicalSourceNotFoundError,
    AstronomicalSourceResolutionError,
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
