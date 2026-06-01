# ADK Quality Lab

Reusable quality-engineering kit for ADK agents.

This repository hosts the public Track 2 (Optimize) submission artifact and a reproducible case study based on Google ADK sample agents.

## Quickstart

```bash
uv sync --extra dev
make ci
```

## Current status

- Baseline public repository scaffold created
- CI placeholder added (`ruff`, `mypy`, `pytest`)
- Package skeleton initialized under `adk_quality_lab/`

## Planning eval variants

- Active: `baseline`, `arch_fix`
- Deferred (not in active eval CLI choices): `prompt_tuning_v1`, `structured_output`, `prompt_tuning_v2`, `markdown`, `json_block`

## License

Apache-2.0. See `LICENSE`.
