# ARTools User Documentation

ARTools can be used through the local web interface or from the command line.
Both interfaces use the same trajectory-generation code.

## Graphical interface

On Linux/macOS:

```bash
./artools-gui
```

On Windows:

```text
artools-gui.cmd
```

The command starts a local web server and opens the ARTools interface in the
default browser. The server listens on `127.0.0.1` by default and is intended
for local use.

The interface is organized around three choices:

1. **Target family**: astronomical source, Solar System body, or artificial satellite.
2. **Mode**: tracking, cross scan, or raster map.
3. **Parameters**: UTC start time, sample interval, requested points, and any target- or mode-specific values.

The generated trajectory is downloaded by the browser using the filename entered
in the Output section.

### Target-specific inputs

**Astronomical source**

Enter a source name that can be resolved by SIMBAD. Network access is required
for the normal SIMBAD lookup. Atmospheric parameters are available under the
advanced options.

**Solar System body**

Supported bodies are:

`sun`, `moon`, `mercury`, `venus`, `mars`, `jupiter`, `saturn`, `uranus`, `neptune`.

Atmospheric parameters are available under the advanced options.

**Artificial satellite**

Provide exactly one of the following:

- a pasted named three-line TLE;
- a TLE text file;
- a satellite name for a live CelesTrak lookup.

A pasted or uploaded TLE can be used without CelesTrak. The optional satellite
refraction correction is available under the advanced options.

### Point-count meaning

The meaning of **Requested points** depends on the selected mode:

- **Tracking**: total number of output points.
- **Cross scan**: requested points per scan leg before legacy odd-count normalization.
- **Raster map**: requested points per side before legacy odd-count normalization.

Cross scan and raster map also expose **Half span**, corresponding to the legacy
`ANG` parameter.

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

A satellite must be supplied either from a local named three-line TLE file:

```text
--tle-file PATH
```

or by an explicit live CelesTrak lookup:

```text
--catalog-name NAME
```

Optional legacy-compatible refraction arguments are:

```text
--refraction
--refraction-frequency-ghz VALUE
--refraction-altitude-m VALUE
```

Example:

```bash
./artools satellite track --tle-file hotbird.tle \
    --start 2026-08-31T12:11:00Z --dt 600 --points 144 \
    --refraction --output hotbird-track.txt
```

## Output files

ARTools writes the legacy Auxiliary Telescope trajectory format: one UTC
timestamp, azimuth, and elevation per line. Existing files are protected by
default in the CLI and are overwritten only when `--force` is supplied.
