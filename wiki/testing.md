# Testing

## CI

- Workflow: `.github/workflows/ci.yml`
- Trigger: PRs + pushes to `main`
- Command: `make ci`

`make ci` includes:

- `make lint` → `ruff check .`
- `make typecheck` → `mypy adk_quality_lab tests`
- `make test` → `pytest`

## Test scope in this repo

- `tests/test_core.py`: schemas, loaders, raters, calibration primitives
- `tests/test_tools.py`: fixture capture dry-run + agent runner helpers
- `tests/test_filter_flights.py`: focused filter logic regression tests in vendored tool
- `tests/test_smoke.py`: package version smoke check

## Notes

- `pyproject.toml` sets `testpaths = ["tests"]`, so `examples/travel-concierge/tests/` are not part of default CI
- Most package tests are offline and deterministic

## Common commands

```bash
make ci
make eval CASE_SET=smoke VARIANT=baseline
make eval CASE_SET=both VARIANT=arch_fix
make kappa
```
