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

This archive has completed **roadmap Step 2: core domain model and Auxiliary
Telescope output writer**.

The package now exposes explicit target-family and trajectory-mode concepts, named
SRT-site and Auxiliary Telescope configuration, validated trajectory data
structures, and a target-independent writer for the selected Auxiliary Telescope
file format. The production target-position calculations, CLI, and GUI are not
implemented yet. See [ROADMAP.md](ROADMAP.md) for the complete implementation
sequence and current project state.

## Installation

From the project root:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -e '.[dev]'
```

## Step 2 Python API

The current public API provides domain vocabulary and output serialization. For
example, a caller can construct a `Trajectory` from UTC `TrajectoryPoint` values
and serialize it with `AuxiliaryTelescopeTrajectoryWriter`. Target-position
providers and trajectory-generation strategies are added in later roadmap steps.

The writer intentionally preserves the legacy `savetrack()` negative-sub-degree
formatting defect for exact compatibility. A value such as `-0.5` degrees is
therefore written as `000:30:00`. This is documented compatibility behavior, not a
new angle-format specification for other controlled systems.

## Tests

Run:

```bash
pytest
```

At Step 2 the test suite verifies the package bootstrap, core domain validation,
the frozen legacy characterization baseline, and exact Auxiliary Telescope writer
compatibility against every valid frozen Step 1 trajectory. The tests do not
require SIMBAD, CelesTrak, or other live astronomy services.

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
