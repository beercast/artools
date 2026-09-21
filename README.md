# ARTools

ARTools is a Python project for generating trajectory files used to move an
auxiliary reference telescope (ART) located at the Sardinia Radio Telescope
(SRT) site. The ART is used as a reference for SRT calibrations.


## Scope

ARTools is designed to generate ART trajectories for three target families:

- astronomical sources;
- Solar System bodies;
- artificial satellites described by TLE data.

For each target family, the intended trajectory modes are:

- tracking;
- cross scan;
- raster map.

The SRT site coordinates are used as observer location for
azimuth/elevation calculations (the ART is located at the SRT site).


## Installation

ARTools requires Python 3.11 or newer. Python itself must already be installed;
the ARTools installer handles the project environment and package dependencies.

From the project directory run:

```bash
python install.py
```

Finally, to launch ARTools:

Linux/macOS:

```bash
./artools --help  # command line
./artools-gui     # graphical user interface
```

Windows:

```text
artools.cmd --help
artools-gui.cmd
```

### Installation details

The installation script creates a virtual environment. To discard the existing
environment and perform a clean reinstall:

```bash
python install.py --recreate
```

For development, including test dependencies and an editable package install:

```bash
python install.py --dev
```

After activating the development environment, tests can be run with:

```bash
pytest
```

## Command-line interface

The command-line interface is available through the local `artools` launcher.
Its command shape is:

```text
./artools astronomical {track,cross-scan,map} ...
./artools solar-system {track,cross-scan,map} ...
./artools satellite {track,cross-scan,map} ...
```

For example:

```bash
./artools astronomical track "W3(OH)" \
    --start 2026-08-31T22:30:00Z --dt 0.5 --points 5 \
    --output w3oh-track.txt

./artools solar-system cross-scan moon \
    --start 2026-08-31T22:30:00Z --dt 0.5 --points 10 \
    --half-span-deg 0.5 --output moon-cross.txt

./artools solar-system map saturn \
    --start 2026-08-31T22:30:00Z --dt 0.5 --points 25 \
    --half-span-deg 0.4 --output saturn-map.txt

./artools satellite track --tle-file hotbird.tle \
    --start 2026-08-31T12:11:00Z --dt 600 --points 144 \
    --refraction --output hotbird-track.txt
```

`--output` is required. Existing files are never replaced implicitly; pass
`--force` to overwrite one. A start time without an explicit timezone is treated
as UTC, while an offset-aware ISO-8601 time is converted to UTC.

Satellite commands accept either `--tle-file` for deterministic offline
operation or `--catalog-name` for a live CelesTrak lookup. Astronomical commands
use SIMBAD through the default application service. See [docs/cli.md](docs/cli.md)
for all nine target-family/trajectory-mode examples and option details.


## Legacy compatibility

The new implementation is derived from the legacy `artools.py` module and its
Jupyter notebook examples. The relevant legacy sources are preserved under
`legacy/original/` as reference material only. They are not installed as part of
the Python package.
