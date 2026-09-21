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


## Documentation

- [User documentation](docs/user.md) - how to start and use ARTools through the graphical interface or the command line, including the CLI commands and options.
- [Developer documentation](docs/developer.md) - development installation, tests, project architecture, and where to modify trajectory-generation behavior.
