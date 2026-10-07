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

SRT is the default observer location for azimuth/elevation calculations. The
graphical interface can also use another observing site.


## Installation

ARTools requires Python 3.11 or newer. Python itself must already be installed;
the ARTools installer handles the project environment and package dependencies.

From the project directory run:

```bash
python install.py
```

Finally, to launch ARTools through the [command-line interface](#command-line-interface) or the graphical interface:

Linux/macOS:

```bash
./artools --help
./artools-gui
```

Windows:

```text
artools.cmd --help
artools-gui.cmd
```

For development installation and test execution, see [Development](#development).

## Functional overview

This section explains what ARTools does from user input to the final trajectory
file. It starts with the functional flow and then gives only the implementation
details needed to understand where each step happens in the code.

### Astronomical source

#### Main flow

For an astronomical source, trajectory generation has four main steps:

1. **Identify the source.** The user starts typing a source name in the web
   interface. ARTools queries the remote SIMBAD service and shows a limited set
   of matching identifiers. The user can refine the search by typing more
   characters, select one of the suggestions, or enter a complete source name
   directly.
2. **Get the source coordinates.** ARTools queries SIMBAD again using the selected
   source name and obtains its equatorial coordinates: right ascension (RA) and
   declination (Dec).
3. **Calculate the source position at the observing site.** From RA/Dec, the
   selected geographical location and the required UTC times, ARTools calculates
   the source azimuth and elevation as seen from that site.
4. **Generate the trajectory.** ARTools applies the selected mode - tracking,
   cross scan or raster map - and produces the sequence of time-tagged
   azimuth/elevation positions written to the Auxiliary Telescope trajectory
   file.

In compact form:

```text
source name
    |
    v
SIMBAD search -> selected source
    |
    v
SIMBAD -> RA / Dec
    |
    v
position at observing site -> Azimuth / Elevation
    |
    v
Tracking / Cross scan / Raster map
    |
    v
Auxiliary Telescope trajectory file
```

#### Implementation details

The browser does not contact SIMBAD directly. The web interface calls the local
FastAPI backend, which uses the
[Astroquery](https://astroquery.readthedocs.io/en/latest/) library to query the
remote SIMBAD service. Astroquery is a third-party Python package for accessing
astronomical web services.

The autocomplete starts after at least two characters have been entered. SIMBAD
search results are intentionally limited, so the GUI states when the displayed
list has reached that limit and asks the user to type more characters to refine
the search. A complete source name can also be entered directly even if it does
not appear in the suggestions. Favorites are stored locally and only help the
user select a source; they do not change the trajectory calculation.

When the user presses `Generate trajectory`, ARTools queries SIMBAD again to
obtain the selected source RA/Dec coordinates. It then uses the
[Astropy](https://www.astropy.org/) library to calculate the corresponding
azimuth and elevation as seen from the selected observing site at each required
time. Finally, the ARTools core applies the selected trajectory mode and writes
the resulting time-tagged positions to the Auxiliary Telescope file.

The responsibilities are therefore:

```text
Source search          -> Astroquery -> SIMBAD
RA/Dec resolution      -> Astroquery -> SIMBAD
Az/El calculation      -> Astropy
Trajectory generation  -> ARTools core
File serialization     -> ARTools core
```

The values submitted by the GUI are collected into a
[`TrajectoryGenerationRequest`](src/artools/application.py), a simple ARTools
object containing everything needed for one generation request: target, observing
site, refraction settings, mode, timing parameters, pointing offsets and mode-specific options.

#### Modifying trajectory generation

If the goal is to change how a trajectory is built, the source lookup and
coordinate calculation normally do not need to change.

The common astronomical part remains:

```text
SIMBAD -> RA / Dec -> Astropy -> base Az / El
                                |
                                v
                     trajectory generation
                                |
                 +--------------+-------------+
                 |              |             |
              Tracking      Cross scan    Raster map
```

The trajectory geometry is implemented in:

- [`tracking.py`](src/artools/tracking.py) for tracking;
- [`cross_scan.py`](src/artools/cross_scan.py) for cross scans;
- [`raster_map.py`](src/artools/raster_map.py) for raster maps.

The main parameters are:

- `Start time`: UTC time of the first trajectory point.
- `Sample interval`: time in seconds between consecutive trajectory points. It
  also determines the times at which the target position is calculated.
- `Requested points`: number of requested samples. Its exact meaning depends on
  the trajectory mode.
- `Half span`: angular half-width used by cross scan and raster map. It is not
  used for tracking.
- `Observing site`: observer location used for azimuth/elevation calculations.
  SRT remains the default.
- Atmospheric refraction: disabled by default. When enabled for astronomical and
  Solar System targets, Astropy uses pressure, temperature, relative humidity and
  observing frequency. The GUI can obtain the atmospheric values for the selected
  site and start time, and they remain editable.
- `Pointing offsets`: optional constant angular offsets on the sky. The azimuth
  offset is converted to an azimuth-axis correction by dividing by
  `cos(elevation)` for each trajectory point; the elevation offset is applied
  directly. Both offsets default to zero.

For `Tracking`, `Requested points` is the total number of trajectory points.

For `Cross scan`, it is the requested number of points per scan leg. ARTools
preserves the legacy behavior of normalizing this value to an odd number when
necessary. The first leg scans in azimuth and the second in elevation.

For `Raster map`, it is the requested number of points per side and is also
normalized to an odd number when necessary. A value of 5 produces a 5 x 5 map,
for a total of 25 trajectory points.

For example, a tracking request with a 1 second sample interval and 5 requested
points calculates positions at:

```text
start time
start time + 1 s
start time + 2 s
start time + 3 s
start time + 4 s
```

#### Output

All modes produce the same internal
[`Trajectory`](src/artools/domain.py): an ordered sequence of points containing
UTC timestamp, azimuth and elevation.

[`AuxiliaryTelescopeTrajectoryWriter`](src/artools/auxiliary_telescope.py)
serializes those points in the legacy-compatible Auxiliary Telescope format, one
point per line:

```text
YYYY/MM/DD HH:MM:SS.mmm, DDD:MM:SS, DDD:MM:SS
```

The three fields are timestamp, azimuth and elevation. Pointing offsets, when
specified, are applied to the generated trajectory before serialization. The file
has no header.

#### Using the [command-line interface](#command-line-interface)

The [command-line interface](#command-line-interface) uses the same ARTools generation logic as the web interface. The main
difference is source selection: the web interface helps the user find a source
through SIMBAD autocomplete and favorites, while the [command-line interface](#command-line-interface) receives the source
name directly as a command-line argument.

For example:

```bash
artools astronomical track "W3(OH)" \
    --start 2026-08-31T22:30:00Z \
    --dt 0.5 \
    --points 5 \
    --output w3oh-track.txt
```

After the source name has been provided, the processing is the same apart from
observer-site selection: the command-line interface uses SRT, while the web
interface uses the selected observing site. ARTools queries SIMBAD for RA/Dec,
generates the requested trajectory, and serializes it in the Auxiliary Telescope
format. The [command-line interface](#command-line-interface) writes the result to the path supplied with `--output`, while the
web interface returns the generated file as a browser download.


### Solar System body

#### Main flow

For a Solar System body, the flow is simpler because there is no external
catalog search.

Trajectory generation has three main steps:

1. **Select the body.** The user chooses one of the Solar System bodies supported
   by ARTools from the web interface.
2. **Calculate the body position at the observing site.** ARTools uses Astropy to
   calculate where that body appears in the sky from the selected site at each
   required UTC time.
3. **Generate the trajectory.** ARTools applies the selected mode - tracking,
   cross scan or raster map - and produces the same kind of time-tagged
   azimuth/elevation trajectory described in the [Astronomical source section](#astronomical-source).

In compact form:

```text
selected Solar System body
    |
    v
Astropy -> body position at observing site -> Azimuth / Elevation
    |
    v
Tracking / Cross scan / Raster map
    |
    v
Auxiliary Telescope trajectory file
```

#### Implementation details

Unlike astronomical sources, Solar System bodies do not need SIMBAD or another
remote catalog. The GUI presents a fixed list of bodies supported by ARTools: Sun, Moon,
Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune.

When the user presses `Generate trajectory`, the selected name is passed to the
[Astropy](https://www.astropy.org/) library. ARTools uses Astropy's built-in
Solar System ephemeris to calculate the body position for the selected observing
site and the required times, and then obtains azimuth and elevation.

Because the built-in ephemeris is used, this calculation does not require an
external network service.

The responsibilities are therefore:

```text
Body selection          -> ARTools GUI
Body position           -> Astropy
Az/El calculation       -> Astropy
Trajectory generation   -> ARTools core
File serialization      -> ARTools core
```

The main ARTools component specific to this target family is
[`AstropySolarSystemPositionCalculator`](src/artools/solar_system.py), which
uses Astropy to calculate the body position at the selected observing site.

[`SolarSystemBody`](src/artools/solar_system.py) defines the Solar System
body names currently accepted by ARTools.

The request is then handled by the same application layer and the same generic
trajectory strategies used for the [Astronomical source](#astronomical-source) target family.

#### Modifying Solar System trajectories

The Solar System calculation provides the base azimuth/elevation position. From
that point onward, tracking, cross scan and raster map use the same trajectory
generation code described in the [Astronomical source section](#astronomical-source):

```text
Astropy -> base Az / El
              |
              v
     trajectory generation
              |
   +----------+-----------+
   |          |           |
Tracking  Cross scan  Raster map
```

Therefore:

- change [`solar_system.py`](src/artools/solar_system.py) if the calculation
  of the Solar System body's position must change;
- change [`tracking.py`](src/artools/tracking.py),
  [`cross_scan.py`](src/artools/cross_scan.py), or
  [`raster_map.py`](src/artools/raster_map.py) if the trajectory geometry or
  timing itself must change.

`Start time`, `Sample interval`, `Requested points`, `Half span`, observing site,
refraction settings, pointing offsets, and the three trajectory modes have the
same meaning described in the [Astronomical source section](#astronomical-source).

The output is also identical: all modes produce a `Trajectory`, which is then
serialized by `AuxiliaryTelescopeTrajectoryWriter` into the Auxiliary Telescope
file format described in the [Astronomical source output section](#output).

#### Using the [command-line interface](#command-line-interface)

The [command-line interface](#command-line-interface) uses the same Solar System calculation and trajectory-generation logic
as the web interface.

The main difference is body selection: instead of choosing the body from the GUI
list, its name is supplied directly as a command-line argument.

For example:

```bash
artools solar-system track mars \
    --start 2026-08-31T22:30:00Z \
    --dt 0.5 \
    --points 5 \
    --output mars-track.txt
```

After the body name has been provided, the processing is the same apart from
observer-site selection: the command-line interface uses SRT, while the web
interface uses the selected observing site. ARTools generates the requested
trajectory and serializes it in the Auxiliary Telescope format.


### Satellite

#### Main flow

For a satellite, ARTools needs TLE orbital data before it can calculate the
target position.

The web interface offers three mutually exclusive TLE sources:

1. **Download fresh TLE.** ARTools downloads the same CelesTrak `geo` catalog
   used by the legacy software and saves it in the ARTools user-data directory.
   If a saved catalog already exists, it is loaded automatically and the button
   is shown as `Refresh` instead of `Download`.
2. **Upload catalog file.** The user selects a local file containing one or more
   named TLE records. ARTools validates it and keeps a copy in its TLE data
   directory. Uploaded catalogs are not loaded automatically on the next start.
3. **Paste TLE manually.** The user pastes one named three-line TLE directly.

For the downloaded and uploaded catalog modes, ARTools reads all satellites in
the file and shows a searchable satellite selector. The user can type part of a
name to filter the list and then select the required satellite.

After one satellite has been selected, trajectory generation has the same two
remaining steps as before:

1. **Calculate the satellite position at the observing site.** ARTools uses
   Pycraf/SGP4 to calculate azimuth and elevation at each required UTC time.
2. **Generate the trajectory.** ARTools applies tracking, cross scan or raster
   map and produces the same time-tagged azimuth/elevation trajectory described
   in the [Astronomical source section](#astronomical-source).

In compact form:

```text
Download CelesTrak GEO catalog --+
                                 |
Upload local TLE catalog --------+--> select satellite
                                 |          |
Paste one named TLE -------------+          v
                                      Pycraf / SGP4
                                           |
                                           v
                                Azimuth / Elevation at observing site
                                           |
                                           v
                              Tracking / Cross scan / Raster map
                                           |
                                           v
                              Auxiliary Telescope trajectory file
```

#### Implementation details

A **TLE** (Two-Line Element Set) describes the orbit of an artificial satellite.
ARTools uses the common named three-line representation: satellite name, TLE
line 1, and TLE line 2. A catalog is simply a sequence of these three-line
records.

The downloaded catalog comes from
[CelesTrak](https://celestrak.org/), using the `geo` group selected by the legacy
ARTools code. The complete catalog is saved locally as `norad_tle.txt`. A saved
downloaded catalog can therefore be used immediately on later runs without a
new network request; `Refresh` replaces it with a fresh copy.

Uploaded catalogs are also copied into the ARTools TLE data directory, but they
are deliberately not selected automatically when ARTools is started again. The
web interface provides an `Open TLE folder` button so the stored files can be
inspected directly.

Once a satellite TLE has been selected, ARTools uses the
[Pycraf satellite library](https://bwinkel.github.io/pycraf/latest/satellite/index.html)
to calculate the satellite position relative to the selected observer location.
Pycraf uses the SGP4 orbit propagator and returns horizontal coordinates including
azimuth, elevation and distance.

The responsibilities are therefore:

```text
TLE source selection    -> ARTools GUI
Catalog download        -> CelesTrak GEO catalog
Catalog storage/search  -> ARTools core
Az/El calculation       -> Pycraf / SGP4
Optional refraction     -> Pycraf
Trajectory generation   -> ARTools core
File serialization      -> ARTools core
```

The main ARTools components specific to satellites are in
[`satellite.py`](src/artools/satellite.py):

- `TleData` stores one named TLE;
- `TleCatalogStore` stores downloaded/uploaded catalogs and selects a satellite
  from them;
- `CelesTrakTleCatalog` downloads the CelesTrak catalog;
- `SatelliteTarget` represents the selected satellite;
- `PycrafSatellitePositionCalculator` calculates the satellite position at the
  selected observing site;
- `PycrafSatelliteRefractionCalculator` provides the optional legacy-compatible
  refraction correction.

After the satellite position provider has been created, the request uses the same
application layer and generic trajectory strategies described for
[astronomical sources](#astronomical-source).

#### Modifying satellite trajectories

The satellite-specific calculation ends when ARTools has obtained the base
azimuth/elevation position:

```text
TLE -> Pycraf / SGP4 -> base Az / El
                              |
                              v
                   trajectory generation
                              |
                  +-----------+-----------+
                  |           |           |
               Tracking   Cross scan  Raster map
```

Therefore:

- change [`satellite.py`](src/artools/satellite.py) if catalog handling,
  CelesTrak access, satellite propagation, or satellite refraction must change;
- change [`tracking.py`](src/artools/tracking.py),
  [`cross_scan.py`](src/artools/cross_scan.py), or
  [`raster_map.py`](src/artools/raster_map.py) if the trajectory geometry or
  timing itself must change.

`Start time`, `Sample interval`, `Requested points`, `Half span`, pointing
offsets, and the three trajectory modes have the same meaning described in the
[Astronomical source section](#astronomical-source).

Satellite refraction is handled separately from astronomical/Solar System
refraction. When enabled, Pycraf applies the legacy-compatible correction using
the observing frequency and selected site altitude; pressure, temperature and
relative humidity are not used by this model.

The output is the same `Trajectory` and Auxiliary Telescope file format described
in the [Astronomical source output section](#output).

#### Using the [command-line interface](#command-line-interface)

The [command-line interface](#command-line-interface) uses the same catalog
selection and trajectory-generation logic. See the
[Artificial satellites](#artificial-satellites) subsection for the available TLE
input modes.

## Command-line interface

On Linux/macOS use the local `./artools` launcher. On Windows use
`artools.cmd`. The examples below use the Linux/macOS form; on Windows replace
`./artools` with `artools.cmd`.

Show the top-level help with:

```bash
./artools --help
```

The command structure is:

```text
./artools astronomical {track,cross-scan,map} ...
./artools solar-system {track,cross-scan,map} ...
./artools satellite {track,cross-scan,map} ...
```

Help is also available for every command, for example:

```bash
./artools astronomical track --help
./artools satellite map --help
```

### Common options

All modes use these options:

| Option | Meaning |
| --- | --- |
| `--start TIME` | ISO-8601 start time. A value without timezone is interpreted as UTC; an offset-aware value is converted to UTC. |
| `--dt SECONDS` | Sample interval in seconds. |
| `--points N` | Point count, with mode-specific meaning described above. |
| `--output PATH` | Output trajectory file. |
| `--force` | Allow an existing output file to be overwritten. |

Cross scan and raster map additionally accept:

```text
--half-span-deg VALUE
```

The default half span is 2 degrees.

### Astronomical sources

Syntax:

```text
./artools astronomical MODE SOURCE [options]
```

The source is resolved through SIMBAD. Optional atmospheric arguments are:

```text
--pressure-hpa
--temperature-c
--relative-humidity
--wavelength-m
```

Example:

```bash
./artools astronomical track "W3(OH)" \
    --start 2026-08-31T22:30:00Z --dt 0.5 --points 5 \
    --output w3oh-track.txt
```

### Solar System bodies

Syntax:

```text
./artools solar-system MODE BODY [options]
```

The body name is case-insensitive. The same optional atmospheric arguments used
for astronomical sources are available.

Example:

```bash
./artools solar-system cross-scan moon \
    --start 2026-08-31T22:30:00Z --dt 0.5 --points 10 \
    --half-span-deg 0.5 --output moon-cross.txt
```

### Artificial satellites

The CLI supports the same three TLE sources as the web interface.

To select a satellite from a local catalog containing multiple records:

```text
--tle-file PATH --satellite NAME
```

A single-record TLE file is also accepted without `--satellite` for backwards
compatibility.

To download a fresh copy of the legacy CelesTrak `geo` catalog, save it in the
ARTools data directory, and select one satellite:

```text
--download-tle --satellite NAME
```

To provide one named three-line TLE directly:

```text
--tle-text TEXT
```

When `--tle-text` is used from a shell, quoting must preserve the three lines.

Optional legacy-compatible refraction arguments are:

```text
--refraction
--refraction-frequency-ghz VALUE
--refraction-altitude-m VALUE
```

Example using a local multi-satellite catalog:

```bash
./artools satellite track \
    --tle-file norad_tle.txt \
    --satellite "EUTELSAT HOTBIRD 13C" \
    --start 2026-08-31T12:11:00Z --dt 600 --points 144 \
    --refraction --output hotbird-track.txt
```

Example downloading fresh TLE data first:

```bash
./artools satellite track \
    --download-tle \
    --satellite "EUTELSAT HOTBIRD 13C" \
    --start 2026-08-31T12:11:00Z --dt 600 --points 144 \
    --output hotbird-track.txt
```

## Development

### Development installation

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

### Checking compatibility with the legacy version

ARTools was rewritten from the original notebooks and `artools.py`, but the new
code must continue to produce the same results when it receives the same input.

To check this, two complementary kinds of tests are used.

The first kind starts from results produced by the legacy software. For some
representative cases, the input data and the corresponding trajectory files
generated by the old implementation were saved and are kept as reference.

The new ARTools is then run with the same input and its output is compared with
those reference files.

In simple terms:

```text
legacy ARTools
same input -> reference output

new ARTools
same input -> output to compare
```

These tests are stored in:

```text
tests/regression/
```

The reference files used for the comparison are stored in:

```text
tests/regression/fixtures/
```

The second kind of test performs a more direct comparison. Instead of using only
a previously saved output file, the test runs both the preserved legacy
calculation and the new ARTools calculation with exactly the same input and then
compares the results.

For example, for a satellite we can use:

```text
same TLE
same start time
same SRT position
same sample interval
same number of points
```

The old satellite calculation and the new one are both executed, and the
resulting timestamps, azimuths and elevations are compared.

These old-versus-new comparison tests are stored in:

```text
tests/physical/
```

`physical` is simply the internal directory name used by the project. In this
context it means that the actual astronomical/orbital calculation performed by
the old implementation is compared with the calculation performed by the new
one.

A concrete example is the HOTBIRD satellite test: both implementations receive
the same fixed TLE and observation parameters, and the resulting satellite
positions must agree within the numerical tolerance used by the test.

After a development installation, both kinds of compatibility checks can be run
together.

Linux/macOS:

```bash
.venv/bin/python -m pytest tests/regression tests/physical
```

Windows:

```text
.venv\Scripts\python.exe -m pytest tests/regression tests/physical
```

This gives a developer two ways to verify compatibility: compare the new output
with results previously produced by the legacy software, and directly compare
the old and new calculations using the same input.

