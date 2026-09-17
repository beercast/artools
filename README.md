# ARTools

ARTools is a Python project for generating trajectory files used to move an
auxiliary telescope (Reference Antenna) located at the Sardinia Radio Telescope
(SRT) site.

## Installation

From the project root:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -e '.[dev]'
```

Astropy-based astronomical and Solar System calculations, together with SIMBAD
resolution support, are isolated in an optional extra. No versions are pinned
yet:

```bash
python -m pip install -e '.[astronomy]'
```

For development with the physical astronomy parity test enabled:

```bash
python -m pip install -e '.[dev,astronomy]'
```
