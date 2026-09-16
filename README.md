# ARTools

ARTools is a Python project for generating trajectory files used to move an
Auxiliary Telescope located at the Sardinia Radio Telescope (SRT) site.

The Auxiliary Telescope is a separate instrument from SRT. Its trajectory files
are loaded into the control software of the Auxiliary Telescope. One important
use of that telescope is to collect information useful for measurements related
to deformations of the SRT surface.

## Scope

The first implementation supports only the Auxiliary Telescope. It is designed
to generate trajectories for three target families:

- astronomical sources;
- Solar System bodies;
- artificial satellites described by TLE data.

For each target family, the intended trajectory modes are:

- tracking;
- cross scan;
- raster map.

The Auxiliary Telescope is located at the SRT site, so the SRT site coordinates
are the correct observer location for azimuth/elevation calculations. This does
not mean that ARTools is controlling SRT.

## Explicitly out of scope for the current application

The legacy software also contains SRT/DISCOS schedule-generation code that can
create `.lis`, `.scd`, `.cfg`, and `.bck` files and contains references such as
`BACKENDS/TotalPower` and `MANAGEMENT/FitsZilla`.

That functionality is not part of the current ARTools application.

The architecture must remain open to adding SRT as a separate controlled system
in the future. If that happens, SRT-specific schedule generation must remain
separate from Auxiliary Telescope trajectory generation because the two control
workflows are fundamentally different.

## Legacy compatibility

The new implementation is derived from the legacy `artools.py` module and its
Jupyter notebook examples. The relevant legacy sources are preserved under
`legacy/original/` as reference material only. They are not installed as part of
the Python package.

The selected Auxiliary Telescope output format is the legacy `savetrack()`
format. `savetrack2()` is not part of the planned output interface unless a
future requirement explicitly reintroduces it.

Before replacing the legacy calculations, deterministic reference outputs must
be produced from the old implementation. Permanent regression tests will then
verify that the new implementation preserves the intended legacy behavior for
equivalent inputs. Differences caused by known legacy defects must be documented
and changed only through an explicit project decision.

## Current status

This archive has completed **roadmap Step 3: astronomical-source tracking**.

The package now supports astronomical-source tracking through Python APIs, with
source resolution isolated from the coordinate transformation and from the generic
tracking loop. The normal adapter uses SIMBAD for name resolution and Astropy for
azimuth/elevation calculation at the SRT site. Deterministic mappings can be used
without network access. Solar System tracking, satellite tracking, cross scans,
raster maps, CLI, and GUI are added in later roadmap steps. See
[ROADMAP.md](ROADMAP.md) for the complete implementation sequence and current
project state.

## Installation

From the project root:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -e '.[dev]'
```

Astronomical calculation and SIMBAD resolution are isolated in an optional extra.
No versions are pinned yet:

```bash
python -m pip install -e '.[astronomy]'
```

For development with the physical astronomy parity test enabled:

```bash
python -m pip install -e '.[dev,astronomy]'
```

## Step 3 Python API

The current public API supports astronomical tracking.
`create_default_astronomical_tracking_service()` creates the normal SIMBAD +
Astropy path. `MappingAstronomicalSourceResolver` can instead supply fixed source
coordinates for deterministic or offline operation. Tracking returns the common
`Trajectory` model, which can then be serialized by
`AuxiliaryTelescopeTrajectoryWriter`.

The writer intentionally preserves the legacy `savetrack()` negative-sub-degree
formatting defect for exact compatibility. A value such as `-0.5` degrees is
therefore written as `000:30:00`. This is documented compatibility behavior, not a
new angle-format specification for other controlled systems.

## Tests

Run:

```bash
pytest
```

At Step 3 the normal test suite verifies the package bootstrap, core domain
validation, frozen legacy characterization, exact Auxiliary Telescope writer
compatibility, generic tracking timing, resolver behavior, and astronomical
tracking compatibility with the Step 1 mechanical reference. No normal test
requires SIMBAD or another live service.

A conditional physical parity test compares the exact preserved legacy Astropy
path with the new Astropy adapter in the same environment. It runs when Astropy
is installed and otherwise reports a skip. See
[docs/astronomical-tracking.md](docs/astronomical-tracking.md).

## Repository layout

```text
artools/
├── src/artools/          # New installable implementation
├── tests/                # Unit, integration, and regression tests
├── docs/                 # Architecture and technical documentation
├── legacy/original/      # Unmodified legacy reference code and notebooks
├── pyproject.toml        # Python build and package metadata
├── README.md             # User-facing project overview
├── ROADMAP.md            # Development plan and cross-chat handoff document
├── CHANGELOG.md          # Planned and unplanned project changes
└── CONTRIBUTING.md       # Development and handoff workflow
```

## Documentation language

All source code, identifiers, comments, docstrings, tests, commit-style notes,
and project documentation must be written in English.
