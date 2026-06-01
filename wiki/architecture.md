# Architecture

## Purpose

`adk-quality-lab` is a quality-evaluation harness around a vendored ADK sample agent (`examples/travel-concierge`).
It enables reproducible before/after comparisons across prompt and architecture variants.

## High-level flow

1. `cli.eval` loads dataset cases (`datasets/*.jsonl`)
2. `tools.agent_runner.build_agent_fn()` loads requested agent variant
3. `runner.run_eval()` executes each case in parallel workers
4. Raters score outputs (`deterministic`, `groundedness`; LLM judge exists but is not on the default eval path — see `known-issues.md #2`)
5. Results persist to local JSONL and optionally Firestore

## Repository map

- `adk_quality_lab/`
  - `cli/`: user-facing commands (`eval`, `optimize`, `kappa`, `dashboard`, `show`)
  - `runner.py`: batch evaluator + persistence glue
  - `datasets/`: Pydantic schema + JSONL loader
  - `raters/`: deterministic, groundedness, and LLM judge logic
  - `tools/`: fixture capture + agent wiring + case generation
  - `optimizer/`: propose/verify tuning loop and clustering
  - `observability/`: Firestore writer + callback stubs
- `examples/travel-concierge/`: vendored baseline agent and tuning variants
- `datasets/`: eval case sets + fixtures + gold labels
- `tests/`: package-level tests used by CI

## Key design decisions

- Keep eval deterministic with cached fixtures (`datasets/fixtures`) for CI and reproducibility
- Keep variant logic isolated in `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/`
- Persist runs locally first (`runs/runs.jsonl`) and Firestore second (best effort)
- Separate expensive judge calibration (`cli.kappa`) from fast CI eval
