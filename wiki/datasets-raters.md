# Datasets & Raters

## Dataset files

- `datasets/f1_count_hallucination.jsonl`
- `datasets/f2_groundedness.jsonl`
- `datasets/tail_flights.jsonl`
- `datasets/gold/f1_gold.jsonl`
- `datasets/gold/f2_gold.jsonl`

## Schema

- `adk_quality_lab/datasets/schema.py`
- Core models:
  - `EvalCase`
  - `RaterResult`
  - `RunResult`

Notable optional fields:

- `expected_flight_count` (F1)
- `expected_values` (F2)
- `start_date`, `end_date`, `search_type` (tail/range cases)
- `gold_label`, `gold_label_rationale` (gold sets)

## Loaders

- `load_all_cases(...)`: canonical loader for F1/F2 (+ optional adversarial/tail)
- `load_smoke_cases(n=30)`: deterministic interleaved subset for fast runs
- `load_gold_cases(...)`: hand-labeled evaluation set

## Raters

### Deterministic (`raters/deterministic.py`)

- `row_count_match`
- `json_schema_validate`
- `iata_membership`
- `numerical_equality`

### Groundedness (`raters/groundedness.py`)

- `structured_value_groundedness` (alias: `agent_eval_groundedness`)

### LLM Judge (`raters/llm_judge.py`)

- `truncation_disclosure`
- `completeness`
- `value_groundedness`
- model: `gemini-2.5-pro`

## Calibration utilities

- `calibration/kappa.py`: Cohen’s κ vs gold labels
- `calibration/bootstrap.py`: score and delta bootstrap CIs
