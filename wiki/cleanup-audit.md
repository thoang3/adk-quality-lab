# Cleanup Audit (Redundant / Unused Candidates)

This page lists deletion or archival candidates discovered in the current codebase.
These are recommendations, not automatic deletions.

## Candidate A — `observability/callbacks.py` (likely dead path)

- **Evidence**: symbol search finds no imports or runtime calls to
  `before_agent_callback`, `after_agent_callback`, or `capture_tool_response`
  outside the file itself.
- **Risk**: low if no external integration relies on these callbacks.
- **Recommendation**: either wire it into runtime properly or remove file + docs.

## Candidate B — `write_rater_result()` (unused function)

- **File**: `observability/firestore_writer.py`
- **Evidence**: no call sites in repository.
- **Risk**: low if not used by external scripts.
- **Recommendation**: remove or mark as explicitly reserved with planned caller.

## Candidate C — `tools/generate_cases.py` (orphaned utility)

- **Evidence**: no references from `Makefile`, CI workflow, or docs; only self-reference.
- **Risk**: medium (may still be used ad hoc locally).
- **Recommendation**: move under `scripts/experimental/` or add an explicit Make target + docs.

## Candidate D — `cli/show.py` (not integrated)

- **Evidence**: no references from `Makefile`/README/CI.
- **Risk**: low; utility is harmless but currently discoverability is poor.
- **Recommendation**: either add a documented Make target (e.g., `make show`) or remove.

## Candidate E — wiring-only optimize artifacts (archive if inactive)

- **Path**: `examples/travel-concierge/adk_quality_lab_wiring/`
  - `agent.py`
  - `eval_reference.py`
  - `train_eval_set.evalset.json`
  - `sampler_config.json`
  - `traces/`
- **Evidence**: no runtime references from `cli.eval`/`runner`; appears dedicated to `adk optimize` experiments.
- **Risk**: medium-high if upcoming optimize work depends on them.
- **Recommendation**: keep but mark as `experimental/` unless optimizer workflow is actively resumed.

## Candidate F — duplicate historical changelog pattern ✅ Resolved

- **Files**: `wiki/log.md` (sole source of truth)
- **Evidence**: a top-level `log.md` no longer exists in the repository. `wiki/log.md` is the canonical session log.
- **Risk**: none — single source of truth already in place.
- **Recommendation**: no action needed; keep all future entries in `wiki/log.md`.
