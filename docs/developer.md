# ARTools Developer Documentation

## Development installation

ARTools requires Python 3.11 or newer.

Create or update the project-local development environment with:

```bash
python install.py --dev
```

This installs the runtime dependencies, development/test dependencies, and the
ARTools package in editable mode inside `.venv`.

To discard the current environment and recreate it from scratch:

```bash
python install.py --recreate --dev
```

Normal development does not require activating the virtual environment. Tests
can be run directly with its Python interpreter.

Linux/macOS:

```bash
.venv/bin/python -m pytest
```

Windows:

```text
.venv\Scripts\python.exe -m pytest
```

After activating `.venv`, the equivalent command is simply:

```bash
pytest
```

## Architecture

ARTools separates target-position calculation from trajectory geometry and from
output serialization.

```text
CLI / Web UI
     |
     v
TrajectoryApplicationService
     |
     +--> target-family service --> horizontal position provider
     |                                |
     |                                +--> SIMBAD/Astropy
     |                                +--> Astropy Solar System
     |                                +--> TLE/Pycraf
     |
     +--> trajectory strategy
     |      +--> tracking
     |      +--> cross scan
     |      +--> raster map
     |
     v
Trajectory
     |
     v
AuxiliaryTelescopeTrajectoryWriter
```

The CLI and web interface are presentation layers only. They both construct a
`TrajectoryGenerationRequest` and call the same synchronous
`TrajectoryApplicationService`.

### Main modules

| Module | Responsibility |
| --- | --- |
| `domain.py` | Core enums and validated data structures: targets, coordinates, trajectory points, common request parameters. |
| `configuration.py` | Named SRT-site and Auxiliary Telescope configuration. |
| `tracking.py` | Generic tracking time sampling. |
| `cross_scan.py` | Generic two-leg cross-scan geometry. |
| `raster_map.py` | Generic square serpentine raster-map geometry. |
| `astronomical.py` | SIMBAD source resolution, Astropy coordinate conversion, and astronomical family services. |
| `solar_system.py` | Supported Solar System targets, Astropy body positions, and Solar System family services. |
| `satellite.py` | TLE handling, Pycraf propagation/refraction, CelesTrak adapter, and satellite family services. |
| `application.py` | High-level request validation, target/mode dispatch, file-generation workflow, and TLE convenience methods. |
| `auxiliary_telescope.py` | Legacy-compatible Auxiliary Telescope trajectory serialization. |
| `cli.py` | Command-line parsing and conversion to application requests. |
| `webapp.py` | FastAPI adapter and web-form to application-request conversion. |
| `web_ui.py` | Server-rendered HTML for the browser interface. |
| `web_assets/` | Local CSS and JavaScript used by the browser interface. |
| `web_launcher.py` | Local Uvicorn server/browser launcher. |

## Where to change trajectory behavior

The most important design rule is: **change the generic trajectory strategy when
the geometry changes, and change a target-family provider when only the target
position calculation changes.**

### Tracking

To change how tracking samples are placed in time, modify:

```text
src/artools/tracking.py
generate_tracking_trajectory()
```

This function is shared by astronomical sources, Solar System bodies, and
satellites. It currently samples point `i` at:

```text
start_time + i * sample_interval
```

Do not modify the three target-family services separately for a change that is
common to tracking geometry/timing.

### Cross scan

To change the cross-scan geometry, modify:

```text
src/artools/cross_scan.py
generate_cross_scan_trajectory()
```

This is the common implementation used by all target families. It contains:

- legacy odd-point normalization;
- the azimuth leg followed by the elevation leg;
- angular-step calculation;
- the `offset / cos(elevation)` azimuth correction.

Family-specific source/body/satellite calculations should normally remain
unchanged when only the scan geometry changes.

### Raster map

To change the map geometry, modify:

```text
src/artools/raster_map.py
generate_raster_map_trajectory()
```

This function contains the common raster behavior:

- legacy odd side-count normalization;
- square `N x N` output;
- serpentine row direction;
- elevation direction derived from target motion;
- per-sample azimuth correction using the current base elevation.

A change to row ordering, spacing, map direction, or offset application belongs
here rather than in the astronomical/Solar System/satellite modules.

## Where to change target positions

If the trajectory geometry is correct but the target position itself must be
calculated differently, change the corresponding family adapter/service.

### Astronomical sources

Use `src/artools/astronomical.py`.

Important components:

- `SimbadAstronomicalSourceResolver`: converts a source name into equatorial coordinates;
- `AstropyAstronomicalPositionCalculator`: converts those coordinates into azimuth/elevation at the SRT site;
- `AstronomicalTrackingService`, `AstronomicalCrossScanService`, `AstronomicalRasterMapService`: bind the astronomical provider to the generic strategies.

### Solar System bodies

Use `src/artools/solar_system.py`.

`AstropySolarSystemPositionCalculator` is responsible for topocentric body
positions. `SolarSystemBody` defines the supported names. The three family
services bind this position provider to the generic trajectory strategies.

### Satellites

Use `src/artools/satellite.py`.

Important components:

- `TleData` / `SatelliteTarget`: explicit satellite input;
- `PycrafSatellitePositionCalculator`: orbital propagation and horizontal position;
- `PycrafSatelliteRefractionCalculator`: optional legacy-compatible refraction;
- `CelesTrakTleCatalog`: isolated network lookup;
- the three satellite services: bind the provider to tracking/cross-scan/raster-map strategies.

A change to CelesTrak lookup should not change propagation or trajectory geometry.
A change to orbital/refraction calculation should not be implemented in
`cross_scan.py` or `raster_map.py`.

## Other common changes

### Output format

Modify `src/artools/auxiliary_telescope.py` only when the Auxiliary Telescope
file format itself must change. `AuxiliaryTelescopeTrajectoryWriter` currently
preserves the legacy timestamp and DMS formatting rules.

### SRT site or controlled-system configuration

Modify `src/artools/configuration.py` for named site/system configuration. Do not
hard-code site values inside trajectory strategies.

### Request routing

Modify `src/artools/application.py` when adding a new target family, trajectory
mode, or application-level option. Scientific formulas should remain in the
family adapters or trajectory strategies.

### CLI

Modify `src/artools/cli.py` for command names, command-line arguments, parsing,
or CLI-specific error handling. The CLI should continue to call the application
service rather than implement scientific logic.

### Web interface

Use:

```text
src/artools/webapp.py
src/artools/web_ui.py
src/artools/web_assets/
```

`webapp.py` converts HTTP/form values into the same application request used by
the CLI. `web_ui.py` and `web_assets/` control presentation and browser behavior.

## Legacy notebook mapping

The preserved legacy implementation is under `legacy/original/`. The main
mapping from the old functions to the new code is:

| Legacy function | New implementation |
| --- | --- |
| `azel()` | `SimbadAstronomicalSourceResolver` + `AstropyAstronomicalPositionCalculator` |
| `pazel()` | `AstropySolarSystemPositionCalculator` |
| `track()` | astronomical position provider + `generate_tracking_trajectory()` |
| `ptrack()` | Solar System position provider + `generate_tracking_trajectory()` |
| `strack()` | Pycraf satellite position provider + `generate_tracking_trajectory()` |
| `xscan()` | astronomical provider + `generate_cross_scan_trajectory()` |
| `pxscan()` | Solar System provider + `generate_cross_scan_trajectory()` |
| `sxscan()` | satellite provider + `generate_cross_scan_trajectory()` |
| `amap()` | astronomical provider + `generate_raster_map_trajectory()` |
| `pmap()` | Solar System provider + `generate_raster_map_trajectory()` |
| `smap()` | satellite provider + `generate_raster_map_trajectory()` |
| `download_tle()` / `tle()` | `CelesTrakTleCatalog` / `TleData` |
| `savetrack()` | `AuxiliaryTelescopeTrajectoryWriter` |

This mapping is the quickest way to locate the new equivalent of code that was
previously changed directly in a notebook or in `artools.py`.

## Tests and compatibility

The test suite is organized by responsibility:

- `tests/test_tracking.py`, `test_cross_scan.py`, `test_raster_map.py`: generic trajectory strategies;
- `tests/test_astronomical.py`, `test_solar_system.py`, `test_satellite.py`: target-family behavior;
- `tests/test_application.py`: shared application routing;
- `tests/integration/test_cli.py`: CLI workflows;
- `tests/integration/test_web.py`: browser/server workflows;
- `tests/regression/`: frozen legacy behavior and output compatibility;
- `tests/physical/`: old/new physical parity when the scientific dependencies are available.

When changing trajectory mathematics, run the focused unit tests first and then
the complete suite. Do not update regression fixtures merely to make a changed
algorithm pass: a deliberate compatibility change should be understood and
recorded explicitly.

Two legacy details are intentionally special:

- the old astronomical `xscan()` contains an undefined-`k` defect; the new generic cross scan implements the intended behavior used by the working planet/satellite versions;
- the Auxiliary Telescope writer preserves the legacy negative-sub-degree sign-loss formatting behavior for compatibility.
