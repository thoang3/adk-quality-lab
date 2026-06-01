# Known Issues

## 1) `cli.optimize` is still scaffold-level

- `adk_quality_lab/cli/optimize.py` uses a stub `run_eval_fn` returning fixed `0.5` scores.
- `_read_instruction()` falls back to placeholder text when `*_current.txt` does not exist.
- Impact: optimization metrics are not currently meaningful without manual wiring.

## 2) LLM judge exists but is not on default eval path

- `runner.run_single_case()` runs deterministic + groundedness raters only.
- `raters/llm_judge.py` and prompt assets exist but are not invoked in default batch runner.
- Impact: `llm_judge.*` IDs in datasets are not scored unless a separate execution path is added.

## 3) Observability callback path is currently disconnected

- `observability/callbacks.py` capture hooks are not imported/injected into the current runner path.
- Tool payload logging to Firestore via callback pathway is therefore inactive by default.

## 4) Surface enum mismatch across CLIs

- `cli/eval.py` allows `root|planning|inspiration`.
- `cli/optimize.py` allows `root|planning|tools`.
- Impact: inconsistent UX and potential confusion for future integrations.

## 5) `arch_fix` count-claim emission is non-deterministic (~80% reliability)

- `planning_agent_arch_fix` instructs the planning agent to open with `"I found N flights for PARAMS."` after
  `flight_search_agent` returns its `CashFlightSummary` JSON.
- On ~20% of runs the LLM skips the sentence and dives directly into listing or clarification,
  causing `row_count_match` to score 0 for that case (rendered-row proxy is too low).
- Observed failures: `tail_001` (SFO→LHR range, no return date given) and `tail_002` (ORD→NRT, single-day fallback).
- Root cause: agent asks a clarifying question before running the search on ambiguous queries, so
  `CashFlightSummary` is never returned and no count claim is made.
- Workaround attempted: `"do NOT ask clarifying questions before this search"` in instruction;
  partially effective but not 100% reliable.
- **Do not** add hardcoded date strings to the instruction to pass specific test cases — that is overfitting.

## 6) `agent_runner` concatenates all text parts (behavioral change from 2026-05-26)

- Prior to 2026-05-26, `_run_agent_async` kept only `last_text` (the final turn's text).
- Changed to accumulate all agent text turns (`all_text_parts`) joined with `"\n\n"`.
- Impact: intermediate sentences (e.g. `"I found N flights…"`) are now preserved in `agent_response`
  and visible to raters. **All variant scores improved or were unaffected by this change.**
- Risk: if a future agent emits very long intermediate reasoning steps, `agent_response` will be
  larger and LLM-judge raters may become more expensive.
