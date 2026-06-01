# Session Log

> **Append-only**. Add a new entry at the bottom each session.
> Format: `## [YYYY-MM-DD] <branch-or-label> | <one-line summary>`

---

## [2026-05-27] wiki-bootstrap | Created adk-quality-lab wiki + cleanup audit

**Work done**:
- Reviewed reference pattern from `travel-concierge/wiki/index.md`, `travel-concierge/wiki/log.md`, and `travel-concierge/.github/copilot-instructions.md`.
- Mapped core `adk_quality_lab` architecture, eval runner, raters, datasets, tools, and CI behavior.
- Created `wiki/` with architecture, eval pipeline, datasets/raters, tools/wiring, testing, known issues, and cleanup audit pages.
- Added concrete deletion/cleanup candidates with evidence in `wiki/cleanup-audit.md`.

**Files changed**:
- `wiki/index.md`
- `wiki/architecture.md`
- `wiki/eval-pipeline.md`
- `wiki/datasets-raters.md`
- `wiki/tools-wiring.md`
- `wiki/testing.md`
- `wiki/known-issues.md`
- `wiki/cleanup-audit.md`
- `wiki/log.md`

**Tests**:
- `make test` result: not run (docs-only changes)
- `make lint` result: not run (docs-only changes)

---

## [2026-05-26] arch-fix-optimize-setup | Backfilled legacy optimize setup notes

**Work done**:
- Created `examples/travel-concierge/adk_quality_lab_wiring/agent.py` exposing `root_agent = planning_agent_v2` for `adk optimize`.
- Created `examples/travel-concierge/adk_quality_lab_wiring/train_eval_set.evalset.json` with 5 training cases (`tail_001`–`tail_005`), intended for optimizer training only.
- Created `examples/travel-concierge/adk_quality_lab_wiring/sampler_config.json` with `response_match_score: 0.5` and `app_name: adk_quality_lab_wiring`.
- Updated `examples/travel-concierge/adk_quality_lab_wiring/tools/fixture_flight_search.py`:
	- added `tool_context=None` to `search_flights`
	- wrote `last_cash_search = {"results": {cabin_key: all_results}}` in both fast-path and fallback of `search_flights_range`
- Updated `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_v2.py` by adding `PLANNING_AGENT_INSTR_ARCH_FIX` instructions to call `get_flight_context()` after `flight_search_agent` summary.
- Updated `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_prompt_v1.py`:
	- restored `from google.genai.types import GenerateContentConfig`
	- restored `generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5)` on `planning_agent_v1`

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/agent.py`
- `examples/travel-concierge/adk_quality_lab_wiring/train_eval_set.evalset.json`
- `examples/travel-concierge/adk_quality_lab_wiring/sampler_config.json`
- `examples/travel-concierge/adk_quality_lab_wiring/tools/fixture_flight_search.py`
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_v2.py`
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_prompt_v1.py`

**Notes**:
- Source backfill: migrated from legacy top-level `log.md` to unify history in `wiki/log.md`.
- `tail_001`–`tail_005` are train-set cases for optimization, not the final held-out comparison set.

**Tests**:
- `make test` result: not recorded in legacy entry

---

## [2026-05-27] wiki-gap-patch | Patched three undocumented behaviors into wiki

**Work done**:
- `wiki/known-issues.md`: added issues #5 (arch_fix count-claim non-determinism, ~20% miss rate on ambiguous queries) and #6 (all_text_parts accumulation behavioral change from 2026-05-26).
- `wiki/eval-pipeline.md`: documented `all_text_parts` concatenation with code snippet and a "do not revert" warning.
- `wiki/tools-wiring.md`: added full `arch_fix` SSE-inject two-tool protocol section — problem statement, mechanism, ADK template-crash explanation, and eval results table.

**Files changed**:
- `wiki/known-issues.md`
- `wiki/eval-pipeline.md`
- `wiki/tools-wiring.md`
- `wiki/log.md`

**Tests**:
- `make test` result: not run (docs-only changes)
- `make lint` result: not recorded in legacy entry

---

## [2026-05-28] planning-variant-audit-plan | Added phased small-start audit plan for tuned prompts

**Work done**:
- Read `wiki/index.md`, `wiki/tools-wiring.md`, and `wiki/known-issues.md` for planning-surface constraints and known risks.
- Reviewed all planning variants under `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/`.
- Added a phased audit plan that starts with `baseline`, `prompt_tuning_v1`, and `arch_fix`.
- Marked `json_block` as deferred for now due to high runtime risk / low near-term decision value.

**Files changed**:
- `.plans/task-planning-variant-audit/plan.md`
- `wiki/log.md`

**Tests**:
- `make ci` result: not run (planning/docs-only session)

---

## [2026-05-28] json-block-defer-move | Moved deferred json_block variant into future bucket with shim

**Work done**:
- Created `tuned_prompts/future/` as a deferred-variant bucket.
- Moved Condition B `json_block` implementation to `tuned_prompts/future/planning_json_block.py`.
- Replaced `tuned_prompts/planning_json_block.py` with a compatibility shim that re-exports symbols,
  preserving `VARIANT=json_block` runtime compatibility.
- Updated wiki/task plan docs to reflect deferred-path location.

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/__init__.py`
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_json_block.py`
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_json_block.py`
- `wiki/tools-wiring.md`
- `.plans/task-planning-variant-audit/plan.md`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_json_block.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_json_block.py` result: pass
- `make ci` result: not run (targeted wiring/doc changes)

---

## [2026-05-28] baseline-archfix-only | Restricted planning variant execution to baseline + arch_fix

**Work done**:
- Updated eval CLI variant choices to allow only `baseline` and `arch_fix`.
- Updated agent runner planning-variant dispatch to load only `baseline`/`arch_fix` and raise for deferred variants.
- Updated task plan to mark all other planning variants as deferred.

**Files changed**:
- `adk_quality_lab/cli/eval.py`
- `adk_quality_lab/tools/agent_runner.py`
- `.plans/task-planning-variant-audit/plan.md`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile adk_quality_lab/cli/eval.py adk_quality_lab/tools/agent_runner.py` result: pass
- `make ci` result: not run (targeted wiring/docs change)

---

## [2026-05-28] docs-variant-policy-sync | Updated README/wiki to baseline+arch_fix active policy

**Work done**:
- Updated `README.md` to list active planning eval variants (`baseline`, `arch_fix`) and deferred variants.
- Updated `wiki/index.md` key facts to reflect active vs deferred planning variant status.

**Files changed**:
- `README.md`
- `wiki/index.md`
- `wiki/log.md`

**Tests**:
- `make ci` result: not run (docs-only changes)

---

## [2026-05-28] future-relocation-cleanup | Moved all deferred planning variants into `tuned_prompts/future/`

**Work done**:
- Relocated deferred modules from top-level `tuned_prompts/` into `tuned_prompts/future/`:
	- `planning_prompt_v1.py`
	- `planning_agent_v2b.py`
	- `planning_markdown.py`
- Removed top-level `planning_json_block.py` shim; deferred implementation remains in `future/planning_json_block.py`.
- Updated deferred module import path in `future/planning_agent_v2b.py`.
- Updated `wiki/tools-wiring.md` important-files list to match new active/deferred layout.

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_prompt_v1.py` (moved)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_v2b.py` (moved + import fix)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_markdown.py` (moved)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_json_block.py` (retained deferred)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_prompt_v1.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_v2b.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_markdown.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_json_block.py` (removed)
- `wiki/tools-wiring.md`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_prompt_v1.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_v2b.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_markdown.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_json_block.py` result: pass
- `make ci` result: not run (targeted wiring/docs changes)

---

## [2026-05-28] active-naming-migration | Renamed active planning modules to `planning_agent_*`

**Work done**:
- Renamed active tuned prompt files:
	- `planning_agent_v2.py` → `planning_agent_arch_fix.py`
	- `planning_baseline.py` → `planning_agent_baseline.py`
- Renamed arch-fix exported symbol in module:
	- `planning_agent_v2` → `planning_agent_arch_fix`
- Updated wiring/runtime imports (`agent_runner.py`, wiring `agent.py`) to new module/symbol names.
- Updated docs (`wiki/tools-wiring.md`, `wiki/known-issues.md`, `examples/travel-concierge/UPSTREAM.md`, task plan).
- Updated focused example unit tests to import the renamed arch-fix module and current symbols.

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_arch_fix.py`
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_baseline.py`
- `adk_quality_lab/tools/agent_runner.py`
- `examples/travel-concierge/adk_quality_lab_wiring/agent.py`
- `examples/travel-concierge/tests/unit/test_flights.py`
- `examples/travel-concierge/UPSTREAM.md`
- `wiki/tools-wiring.md`
- `wiki/known-issues.md`
- `.plans/task-planning-variant-audit/plan.md`
- `wiki/log.md`

**Tests**:
- `uv run pytest examples/travel-concierge/tests/unit/test_flights.py -q` result: pass (12 passed)
- `uv run python -m py_compile adk_quality_lab/tools/agent_runner.py examples/travel-concierge/adk_quality_lab_wiring/agent.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_arch_fix.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_baseline.py` result: pass
- `make ci` result: not run (targeted wiring/docs changes)

---

## [2026-05-28] deferred-naming-normalization | Renamed all deferred future modules to `planning_agent_*`

**Work done**:
- Renamed deferred module files in `tuned_prompts/future/`:
	- `planning_prompt_v1.py` → `planning_agent_prompt_tuning_v1.py`
	- `planning_agent_v2b.py` → `planning_agent_prompt_tuning_v2.py`
	- `planning_markdown.py` → `planning_agent_markdown.py`
	- `planning_json_block.py` → `planning_agent_json_block.py`
- Updated deferred prompt-tuning-v2 module internals:
	- import path now points to `tuned_prompts.future.planning_agent_prompt_tuning_v1`
	- symbol names normalized from `*_v2b` to `*_prompt_tuning_v2`
- Updated deferred filename references in docs/plans.

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_prompt_tuning_v1.py` (renamed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_prompt_tuning_v2.py` (renamed + internal symbol/import updates)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_markdown.py` (renamed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_json_block.py` (renamed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_prompt_v1.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_v2b.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_markdown.py` (removed)
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_json_block.py` (removed)
- `wiki/tools-wiring.md`
- `.plans/task-planning-variant-audit/plan.md`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_prompt_tuning_v1.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_prompt_tuning_v2.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_markdown.py examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/future/planning_agent_json_block.py` result: pass
- `make ci` result: not run (targeted wiring/docs changes)

**Follow-up note**:
- Attempted `make ci` after this change set; failed at `ruff` config load because
	`examples/travel-concierge/pyproject.toml` extends missing parent file
	`/Users/thoang3/workspace/thoang3/pyproject.toml` in the current environment.

---

## [2026-05-28] baseline-docstring-audit-fix | Corrected two baseline-vs-upstream docstring claims

**Work done**:
- Updated `planning_agent_baseline.py` docstring to match implementation and upstream comparison:
	- corrected tool count from one tool to two (`search_flights`, `search_flights_range`)
	- replaced outdated schema omission claim with accurate wording about no additional schema constraints beyond upstream defaults

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_baseline.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/planning_agent_baseline.py` result: pass
- `make ci` result: not run (targeted docs/commentary change)

---

## [2026-05-28] entrypoint-split-default-vs-eval | Switched default wiring to upstream root and isolated eval root

**Work done**:
- Updated `examples/travel-concierge/adk_quality_lab_wiring/agent.py` to use upstream default root agent (`travel_concierge.agent.root_agent`).
- Added `examples/travel-concierge/adk_quality_lab_wiring/agent_eval.py` to keep harness/eval root (`planning_agent_arch_fix`) isolated.
- Updated `wiki/tools-wiring.md` to document the new entrypoint split.

**Files changed**:
- `examples/travel-concierge/adk_quality_lab_wiring/agent.py`
- `examples/travel-concierge/adk_quality_lab_wiring/agent_eval.py`
- `wiki/tools-wiring.md`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile examples/travel-concierge/adk_quality_lab_wiring/agent.py examples/travel-concierge/adk_quality_lab_wiring/agent_eval.py` result: pass
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] baseline-trace-script | Added runnable baseline trace script with verbose agent/tool logging

**Work done**:
- Added `scripts/run_baseline_trace.py` to trace end-to-end query flow with explicit logs for:
	- loaded root agent and agent tree (sub-agents/tools)
	- runtime ADK event stream
	- function call / function response parts (when present)
	- final user-visible response text
- Script supports `--variant baseline|arch_fix`, `--surface`, `--query`, and optional `--fixture-hash` preload.

**Files changed**:
- `scripts/run_baseline_trace.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/run_baseline_trace.py` result: pass
- `uv run python scripts/run_baseline_trace.py --help` result: pass
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] disentangle-root-baseline-routing | Restored upstream root file and routed `surface=root` planning to baseline
**Work done**:
- Restored vendored upstream file `examples/travel-concierge/travel_concierge/agent.py` to upstream composition (`planning_agent`), removing direct dependency on wiring modules.
- Restored `examples/travel-concierge/adk_quality_lab_wiring/agent.py` to mirror-upstream entrypoint (`root_agent = upstream_root_agent`).
- Updated `adk_quality_lab/tools/agent_runner.py` so `_load_root_agent(..., surface="root", ...)` now swaps the root graph's `planning_agent` sub-agent to `planning_agent_baseline` at load time.
- Kept planning-surface variant loading unchanged (`baseline|arch_fix`).

**Files changed**:
- `examples/travel-concierge/travel_concierge/agent.py`
- `examples/travel-concierge/adk_quality_lab_wiring/agent.py`
- `adk_quality_lab/tools/agent_runner.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile adk_quality_lab/tools/agent_runner.py examples/travel-concierge/travel_concierge/agent.py examples/travel-concierge/adk_quality_lab_wiring/agent.py` result: pass
- Runtime verification: `_load_root_agent(example_dir, "root", "baseline")` includes planning sub-agent identity-equal to `tuned_prompts.planning_agent_baseline`.
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] trace-log-file-routing | Routed trace/debug output to file (`backend.log`)
**Work done**:
- Updated `scripts/run_baseline_trace.py` to add `--log-file` (default: `backend.log`).
- Logging now writes to both stdout and file via handlers with timestamped format.
- Script now logs the resolved log-file path and final response length for easier debugging.

**Files changed**:
- `scripts/run_baseline_trace.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/run_baseline_trace.py` result: pass
- `uv run python scripts/run_baseline_trace.py --variant baseline --surface root --query "Find economy flights from SFO to NRT on 2026-09-12" --log-level DEBUG --log-file backend.log` result: pass
- Verified `backend.log` contains runtime event trace and model/tool debug logs.
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] trace-baseline-identity-marker | Added explicit root→baseline wiring proof in logs
**Work done**:
- Updated `scripts/run_baseline_trace.py` to log an explicit wiring check for `surface=root`.
- Added `Root planning wiring check: planning_agent_baseline_identity=<bool>` and target symbol log line.
- This removes ambiguity where ADK agent `name` remains `planning_agent` even when the object identity is baseline wiring.

**Files changed**:
- `scripts/run_baseline_trace.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/run_baseline_trace.py` result: pass
- `uv run python scripts/run_baseline_trace.py --variant baseline --surface root --query "Find economy flights from SFO to NRT on 2026-09-12" --log-level INFO --log-file backend.log` result: pass
- Verified `backend.log` contains:
	- `Root planning wiring check: planning_agent_baseline_identity=True`
	- `Root planning wiring target symbol: tuned_prompts.planning_agent_baseline.planning_agent_baseline`
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] serpapi-live-verifier-script | Added minimal live SerpAPI checker script in this repo
**Work done**:
- Added `scripts/verify_serpapi_live.py` to verify real `google_flights` SerpAPI calls in `adk-quality-lab`.
- Script logs to file (`backend.log` by default), saves raw response JSON (`serpapi_response.json` by default), and prints a concise flight summary.
- Script exits with clear status codes for missing key, API errors, and empty-flight results.

**Files changed**:
- `scripts/verify_serpapi_live.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/verify_serpapi_live.py` result: pass
- `uv run python scripts/verify_serpapi_live.py --origin SFO --destination NRT --date 2026-09-12 --log-level INFO --log-file backend.log --dump-json serpapi_response.json` result: fail (expected in current env) — `SERP_API_KEY is not set`
- `make ci` result: not run (environment still blocked on missing parent Ruff config file)

---

## [2026-05-28] baseline-trace-fixture-gap-verified | Verified root cause and restored real flight output
**Work done**:
- Ran `scripts/run_baseline_trace.py` with `surface=planning` and confirmed tool-call chain executes:
	- `planning_agent -> flight_search_agent -> search_flights`
- Confirmed previous no-flight behavior was caused by missing fixture for query/date, not SerpAPI outage.
- Captured missing fixture via `adk_quality_lab.tools.capture_fixtures` for `SFO-NRT` on `2026-09-12`.
- Re-ran trace and verified fixture hit plus 5 flight options returned.

**Files changed**:
- `datasets/fixtures/flights/73fe51c7d9e8a49e719336c0739cbb57c2a74198c9adbde2e2fe900d30fe5598.json` (new economy fixture)
- `datasets/fixtures/flights/de3352a3663efa2024d59d734d091319a931a32e8c98e6a1a83f0f051dcc53b6.json` (new business fixture)
- `datasets/fixtures/index.json` (fixture index updated)
- `wiki/log.md`

**Tests**:
- `uv run python -m adk_quality_lab.tools.capture_fixtures --routes SFO-NRT --date-offsets 107` result: pass (2 fixtures fetched)
- `uv run python scripts/run_baseline_trace.py --variant baseline --surface planning --query "Find economy flights from SFO to NRT on 2026-09-12 and show me 5 options with prices" --log-level INFO --log-file backend.log` result: pass (function call observed, 5 options returned)
- `make ci` result: not run (debug/fixture-capture session)

**Follow-up risk**:
- Baseline is fixture-backed by design; new route/date queries need fixture capture before trace/eval.

---

## [2026-05-28] trace-speaker-labels | Added explicit speaker labels for runtime trace events
**Work done**:
- Updated `scripts/run_baseline_trace.py` runtime event logging to include event speaker (`event.author` fallback to `agent_name`).
- Event lines now print `speaker=<agent>` and message lines now print `[speaker]` for:
	- text parts
	- function calls
	- function responses
- This makes it explicit which agent is currently talking during root/planning/sub-agent handoffs.

**Files changed**:
- `scripts/run_baseline_trace.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/run_baseline_trace.py` result: pass
- `uv run python scripts/run_baseline_trace.py --help` result: pass
- `make ci` result: not run (targeted script update)

---

## [2026-05-28] trace-flight-before-after-payload | Printed flight_search_agent return payload before planning synthesis
**Work done**:
- Updated `scripts/run_baseline_trace.py` to print explicit handoff content blocks:
	- `[BEFORE planning_agent] flight_search_agent returned:` with full JSON payload.
	- `[AFTER planning_agent] text passed to user:` with full synthesized planning response.
- Kept existing speaker-tagged event logs so payload blocks are tied to agent identity.

**Files changed**:
- `scripts/run_baseline_trace.py`
- `wiki/log.md`

**Tests**:
- `uv run python -m py_compile scripts/run_baseline_trace.py` result: pass
- `uv run python scripts/run_baseline_trace.py --variant baseline --surface planning --query "Find economy flights from SFO to NRT on 2026-09-12 and show me 5 options with prices" --log-level INFO --log-file backend.log` result: pass
- Verified `backend.log` includes both:
	- `[BEFORE planning_agent] flight_search_agent returned:`
	- `[AFTER planning_agent] text passed to user:`
- `make ci` result: not run (targeted trace instrumentation)
