# Task Plan — Planning Variant Audit (Start Small)

## Goal

Audit all planning variants under `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/`
without over-scoping. Prioritize a minimal set that gives high signal on quality and reliability,
then expand only if findings justify it.

## Scope Inventory

- `planning_agent_baseline.py` (`baseline`, Condition C)
- `planning_agent_prompt_tuning_v1.py` (`prompt_tuning_v1`, C + stricter prompt)
- `planning_agent_prompt_tuning_v2.py` (`prompt_tuning_v2`, C + tuned tool descriptions)
- `planning_agent_markdown.py` (`markdown`, Condition A regression reference)
- `planning_agent_json_block.py` (`json_block`, Condition B regression reference)
- `planning_agent_arch_fix.py` (`arch_fix`, Condition D target architecture)

## Active Audit Set (Phase 1)

Only these 2 are active:

1. `baseline` — control for all comparisons.
2. `arch_fix` — target architecture and default candidate.

Why this set:
- Minimal, high-signal comparison aligned with current scope constraints.
- Fastest path to a default planning variant decision.

## Deferred Variants

Deferred for now:

- `planning_agent_prompt_tuning_v1.py` (`prompt_tuning_v1`)
- `planning_agent_prompt_tuning_v2.py` (`prompt_tuning_v2`)
- `planning_agent_markdown.py` (`markdown`)
- `planning_agent_json_block.py` (`json_block`)

Rationale:
- Keep evaluation focus strictly on control (`baseline`) vs architecture fix (`arch_fix`).
- Reduce run/time cost and interpretation overhead.
- Re-enable only if publication/replication requirements demand it.

## Phased Audit Sequence

### Phase 1 — Fast Signal (2 variants)

- Variants: `baseline`, `arch_fix`
- Case set: `smoke`, then `tail`/`both` if smoke looks clean
- Focus metrics:
  - F1 row-count behavior / count-claim reliability
  - F2 grounded value fidelity
  - run stability and timeout incidence

Decision gate to proceed:
- If `arch_fix` clearly dominates `baseline` and is stable, treat as default winner for planning surface.

### Phase 2 — Deferred Re-entry (optional)

- Re-enable one deferred variant only if we need additional attribution detail.

### Deferred / Future

- All non-`baseline` / non-`arch_fix` variants stay deferred unless publication replication requires them.

## Concrete Execution Checklist

1. Create audit worksheet with one row per variant and fields: aggregate, F1, F2, latency, notable failures.
2. Run `smoke` across Phase 1 variants first.
3. Run expanded set only for variants that pass smoke.
4. Capture 3 representative failure traces per failing variant.
5. Decide keep / iterate / defer per variant.

## Exit Criteria

- We can name one default planning variant with evidence.
- We can justify selecting `arch_fix` or retaining `baseline` as default.
- Deferred variants are explicitly documented with rationale and re-entry conditions.