# Change Log

## 2026-05-26

### adk optimize setup (arch_fix)
- Created `examples/travel-concierge/adk_quality_lab_wiring/agent.py` — exposes `root_agent = planning_agent_v2` for `adk optimize`
- Created `train_eval_set.evalset.json` — 5 train cases (tail_001–005), expected responses capture correct count + full list
- Created `sampler_config.json` — `response_match_score: 0.5`, `app_name: adk_quality_lab_wiring`
- NOTE: tail_001–005 are the TRAIN set for optimization only. Final variant comparison must use a separate held-out test set.

### fixture_flight_search.py
- Added `tool_context=None` param to `search_flights`
- After loading fixture, writes `last_cash_search = {"results": {cabin_key: all_results}}` into session state so `get_flight_context` (arch_fix) can read it
- Same write added to fast-path and fallback of `search_flights_range`

### planning_agent_v2.py (arch_fix variant)
- Added `PLANNING_AGENT_INSTR_ARCH_FIX` — appends instruction forcing agent to call `get_flight_context()` after `flight_search_agent` returns summary
- Uses `FunctionTool(get_flight_context)` directly — examples version is cash-only by design (no `search_type` param), no wrapper needed

### planning_prompt_v1.py (prompt_tuning_v1 variant)
- Restored `from google.genai.types import GenerateContentConfig` import
- Restored `generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5)` on `planning_agent_v1` (matches private repo `agent.py`)
