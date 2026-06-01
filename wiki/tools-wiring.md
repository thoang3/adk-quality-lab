# Tools & Wiring

## Core tools

- `tools/agent_runner.py`
  - Converts fixture payloads to `travel_concierge` session state
  - Loads variant-specific agents from `adk_quality_lab_wiring/tuned_prompts`
  - Supports retry/backoff on 429 errors
- `tools/capture_fixtures.py`
  - Calls SerpAPI `google_flights`
  - Caches deterministic fixture JSON by SHA-256 key
  - Maintains `datasets/fixtures/index.json`
- `tools/generate_cases.py`
  - Generates F1/F2 JSONL datasets from captured fixtures

## Vendored wiring layer

Path: `examples/travel-concierge/adk_quality_lab_wiring/`

Primary purpose:

- keep baseline and tuned variants isolated from upstream vendored source
- support reproducible variant selection in eval runs

Important files:

- `agent.py` — default app entrypoint (mirrors upstream `travel_concierge.agent.root_agent`)
- `agent_eval.py` — harness/eval entrypoint (`root_agent = planning_agent_arch_fix`)
- `tuned_prompts/planning_agent_baseline.py` — active control variant
- `tuned_prompts/planning_agent_arch_fix.py` — active `arch_fix` variant (SSE-inject two-tool protocol; see section below)
- `tuned_prompts/future/planning_agent_prompt_tuning_v1.py` — deferred
- `tuned_prompts/future/planning_agent_prompt_tuning_v2.py` — deferred
- `tuned_prompts/future/planning_agent_markdown.py` — deferred
- `tuned_prompts/future/planning_agent_json_block.py` — deferred
- `tools/fixture_flight_search.py`

## `arch_fix` variant — SSE-inject two-tool protocol

Defined in `tuned_prompts/planning_agent_arch_fix.py`. This is the primary hackathon contribution.

**Problem it solves**: baseline variants ask `flight_search_agent` to enumerate all flights inline.
With 80–150 results the LLM truncates or mutates values (truncation collapse).

**How it works**:

1. `flight_search_agent_lazy` uses `output_schema=CashFlightSummary` and
   `response_mime_type="application/json"`.  
   It calls `search_flights` / `search_flights_range`, writes the full raw list to
   `session_state["search_results_cash"]`, then returns only:
   ```json
   {"total_found": 95, "search_params": "ORD→NRT, Business, Jul 1-7"}
   ```
   (~10 tokens, no flight enumeration).

2. `planning_agent` receives this lean JSON, emits  
   `"I found 95 flights for ORD→NRT, Business, Jul 1-7."`  
   then calls `get_flight_context()` to pull flights from session state on demand.

3. `get_flight_context()` reads `search_results_cash` and applies server-side filters
   (`num_stops`, `max_price`, `airline`, time windows) — the LLM never synthesises large lists.

**Why `CashFlightSummary` avoids the ADK template crash**:  
Earlier attempts used `{total_found}` as prose in the instruction string. ADK resolves
`{varname}` tokens via session-state injection at runtime → `KeyError`. The schema approach
bypasses this entirely because the count travels as structured data, not as a template token.

**Eval results (tail set, 2026-05-26)**:
| Variant | Aggregate |
|---|---|
| baseline | 0.603 |
| prompt_tuning_v2 | 0.536 |
| arch_fix | **0.900** |

## Observability integration

- `observability/firestore_writer.py`
  - actively used for run-level writes (`write_run_result`)
- `observability/callbacks.py`
  - currently present but not wired into runtime path (see `cleanup-audit.md`)
