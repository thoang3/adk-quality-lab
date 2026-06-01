source: https://github.com/google/adk-samples
path:   python/agents/travel-concierge
commit: 964b975ee158a01e9f61fa52d432b49ed4a396d4
copied: 2026-05-24
license: Apache-2.0 (see LICENSE in google/adk-samples)

## Baseline isolation guarantee

Running `make eval CASE_SET=both VARIANT=baseline` loads
`adk_quality_lab_wiring/tuned_prompts/planning_agent_baseline.py`, which is the
vanilla upstream planning agent plus **one minimal addition**: a fixture-backed
`search_flights` FunctionTool wired into `flight_search_agent`.

### Why the tool addition is necessary (not optional)

The vanilla upstream `flight_search_agent` has **no tools** — it generates
`FlightsSelection` purely from LLM weights (hallucination). Running eval
against that measures "hallucination vs. SerpAPI reality," which is not a
meaningful quality signal because:

- It cannot be improved by prompt tuning (no data flows through the agent)
- Every result would "fail" regardless of instruction quality
- The failure mode would be identical for all 5 variants

The meaningful baseline is: **real SerpAPI data flows through the agent, the
LLM synthesizes it, the rater checks faithfulness**. F1/F2 failures then
reflect actual synthesis errors (value mutation, truncation without disclosure)
that prompt tuning and architectural changes can measurably reduce.

### What `planning_agent_baseline.py` changes vs. upstream

| Item | Upstream | Baseline |
|---|---|---|
| `planning_agent` instruction | `PLANNING_AGENT_INSTR` | **identical** |
| `flight_search_agent` instruction | hallucination prompt | tool-use prompt (minimal) |
| `flight_search_agent` tools | `[]` (none) | `[search_flights]` (fixture-backed) |
| `flight_search_agent` output_schema | `FlightsSelection` | **identical** |
| `hotel_search_agent` | unchanged | **identical** |
| `flight_seat_selection_agent` | unchanged | **identical** |
| `itinerary_agent` | unchanged | **identical** |

### Intentional omissions in `FLIGHT_SEARCH_INSTR_BASELINE`

These are the failures the baseline is designed to exhibit:
- **No truncation-disclosure instruction** → F1 failures (added in `prompt_tuning_v1`)
- **No verbatim-citation constraint** → F2 failures (added in `prompt_tuning_v1`)
- **No structured JSON schema enforcement** (added in `structured_output`)

### Files byte-identical to upstream

- `travel_concierge/__init__.py`
- `travel_concierge/sub_agents/planning/agent.py`
- `travel_concierge/sub_agents/planning/prompt.py`

