# Eval Pipeline

## Entry point

- `adk_quality_lab/cli/eval.py`
- Core flags:
  - `--case-set`: `f1 | f2 | both | smoke | gold | tail`
  - `--variant`: `baseline | prompt_tuning_v1 | structured_output | prompt_tuning_v2 | arch_fix | markdown | json_block`
  - `--surface`: `root | planning | inspiration`
  - `--stub`: skip live agent execution and return a fixed placeholder response; useful for testing rater/scoring logic in isolation without requiring a working agent or fixtures

## Execution stages

1. Load cases via `datasets.loader`
2. Patch Firebase import to local stub (`_patch_firebase`)
3. Build variant-specific callable via `tools.agent_runner.build_agent_fn`
4. Run cases with `runner.run_eval` (thread pool)
5. Aggregate score + category scores
6. Persist run:
   - local: `runs/runs.jsonl`
   - optional Firestore: `observability.firestore_writer.write_run_result`

## Fixtures

- `runner.load_fixture()` resolves full SHA or 24-char prefix
- `runner.load_range_fixture()` merges per-day fixtures for range cases (`tail_flights.jsonl`)
- In-session state conversion happens in `tools.agent_runner._fixture_to_session_state`

## Current behavior notes

- Parallelism uses `ThreadPoolExecutor` (not process pool) to avoid pickling constraints with ADK objects
- `run_eval()` currently runs deterministic + groundedness raters only
- LLM-judge raters are available in code but not wired into `run_eval()` default path

## Agent response accumulation (changed 2026-05-26)

`_run_agent_async` in `tools/agent_runner.py` collects **all** text parts emitted across every
event in the ADK run loop, not just the final one:

```python
all_text_parts: list[str] = []
for event in runner.run_async(...):
    for part in event.content.parts:
        if part.text:
            all_text_parts.append(part.text)
return "\n\n".join(all_text_parts)
```

This means raters see the full conversation trace — including intermediate count announcements
(`"I found N flights for …"`) emitted before tool calls — not just the final synthesised listing.
Do **not** revert this to `last_text` only; it would silently drop count claims for `arch_fix`.
