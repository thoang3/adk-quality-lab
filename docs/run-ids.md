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
| planning | smoke | 189ad58f-0679-490d-b7e8-b6645bdc779b | 2026-05-26 | 0.547 | 0.900 | 0.311 |
| planning | both  | 36a177cc-57d0-4896-b4d4-b86d3f8d77d6 | 2026-05-26 | 0.572 | 0.940 | 0.327 |

## Tuned runs

| Surface | Variant | Category | Run ID | Date | Aggregate | F1 | F2 | Δ Aggregate |
|---------|---------|----------|--------|------|-----------|----|----|-------------|
| planning | prompt_tuning_v1  | both | 51d0fe3d-4a2c-43c4-8955-9e76d4cba1bd | 2026-05-26 | 0.576 | 0.950 | 0.327 | +0.004 |
| planning | structured_output | both | 91cbe068-a828-41a0-b69b-ae8420035ad5 | 2026-05-26 | 0.564 | 0.930 | 0.320 | -0.008 |
| planning | prompt_tuning_v2  | both | 8760227f-3070-4041-bebe-d67ad416b4d9 | 2026-05-26 | 0.568 | 0.930 | 0.327 | -0.004 |
| planning | arch_fix          | both | (pending) | | | | | |

## κ measurements

| Rater | κ | n | Date |
|-------|---|---|------|
| llm_judge.truncation_disclosure | (TBD Day 5) | 15 | |
| llm_judge.value_groundedness | (TBD Day 5) | 15 | |
| groundedness.structured_value | (TBD Day 5) | 15 | |
