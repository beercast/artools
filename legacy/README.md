# Legacy reference sources

`legacy/original/` contains the original ARTools source and the trajectory
notebooks supplied at project bootstrap.

These files exist only to characterize and test compatibility with the old
behavior. They are outside the `src/` package and must not be imported by normal
application code.

The original `artools.py` contains both Auxiliary Telescope trajectory logic and
SRT/DISCOS schedule-generation logic. Its presence here does not make the latter
part of the new application's scope.

The SRT-only `s_oof.ipynb` notebook is intentionally not copied into this
trajectory-focused reference set because the current application explicitly
excludes SRT schedule generation. The original `artools.py` is preserved
unchanged, including its historical scheduling functions, so the source snapshot
remains useful for forensic comparison.
