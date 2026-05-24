# Canonical BigQuery Run IDs

All claimed numbers in the README and submission are traceable to the BigQuery
run IDs listed here. To reproduce any number:

```bash
make eval CASE_SET=both VARIANT=<variant>
```

Then compare the output `run_id` with the entries below.

## Baseline runs

| Surface | Category | Run ID | Date | Aggregate | F1 | F2 |
|---------|----------|--------|------|-----------|----|----|
| (to be filled after Day 3-4 eval) | | | | | | |

## Tuned runs

| Surface | Category | Run ID | Date | Aggregate | F1 | F2 | Δ |
|---------|----------|--------|------|-----------|----|----|---|
| root | both | (TBD Day 7) | | | | | |
| planning | both | (TBD Day 7) | | | | | |
| tools | both | (TBD Day 7) | | | | | |

## κ measurements

| Rater | κ | n | Date |
|-------|---|---|------|
| llm_judge.truncation_disclosure | (TBD Day 5) | 15 | |
| llm_judge.value_groundedness | (TBD Day 5) | 15 | |
| groundedness.structured_value | (TBD Day 5) | 15 | |
