"""Wired prompt_tuning_v2 planning agent for ADK Quality Lab eval.

VARIANT=prompt_tuning_v2 — Optimizer-tuned tool descriptions on top of structured_output.

What changes vs. structured_output:
  1. flight_search_agent.description is replaced with an Optimizer-tuned
     description that clarifies routing semantics and deduplication behaviour,
     reducing the planning_agent's tendency to call the tool redundantly.
  2. Truncation-disclosure + verbatim-citation instructions are retained from
     prompt_tuning_v1 / structured_output.

What does NOT change vs. structured_output:
  - planning_agent instruction — identical to upstream PLANNING_AGENT_INSTR
  - FlightsSelection output_schema — identical
  - planning_agent tools list — identical
  - All other sub-agents (hotel, seat, itinerary) — identical

Expected improvement vs. structured_output (per §7 target table):
  F1 truncation-disclosure rate:  ≥ 75% → ≥ 90%  (+15pp)
  F2 structured value match:      ≥ 97% → ≥ 98%  (+1pp)

Optimizer run that produced this variant:
  make optimize SURFACE=tools ITERS=20
  (tool_description_tuner accepted this candidate at iteration 2)

NOTE: This is the second-to-last phase. arch_fix (planning_agent_arch_fix.py) is the
final architecture that supersedes this variant in end-to-end quality.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL  # type: ignore[import-untyped]
from travel_concierge.shared_libraries import types  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning import prompt  # type: ignore[import-untyped]
from travel_concierge.tools.memory import memorize  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning.agent import (  # type: ignore[import-untyped]
    hotel_room_selection_agent,
    hotel_search_agent,
    flight_seat_selection_agent,
    itinerary_agent,
)

from tools.fixture_flight_search import search_flights, search_flights_range  # type: ignore[import-untyped]
from tuned_prompts.future.planning_prompt_v1 import FLIGHT_SEARCH_INSTR_V1  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Optimizer-tuned tool description for flight_search_agent.
# Targets reduction in redundant tool calls and improves routing precision.
# ---------------------------------------------------------------------------

FLIGHT_SEARCH_AGENT_DESC_V2 = (
    "Searches for available cash flights on a specific route and date using "
    "SerpAPI Google Flights data (fixture-backed for eval determinism). "
    "Call this agent exactly once per (origin, destination, outbound_date, cabin_class) "
    "combination. Do NOT call it multiple times for the same route — results are "
    "deduplicated server-side. Returns a FlightsSelection JSON with verbatim field "
    "values (carrier codes, prices, times) and an explicit truncation disclosure "
    "header when the result set is larger than the response window."
)

# ---------------------------------------------------------------------------
# flight_search_agent_v2b: tuned description + schema enforcement + tuned instruction.
# ---------------------------------------------------------------------------

flight_search_agent_v2b = Agent(
    model=MODEL,
    name="flight_search_agent",
    description=FLIGHT_SEARCH_AGENT_DESC_V2,
    instruction=FLIGHT_SEARCH_INSTR_V1,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    output_schema=types.FlightsSelection,
    output_key="flights",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    generate_content_config=types.json_response_config,
)

# ---------------------------------------------------------------------------
# planning_agent_v2b: planning agent with tuned tool descriptions.
# ---------------------------------------------------------------------------

planning_agent_v2b = Agent(
    model=MODEL,
    description=(
        "Helps users with travel planning, complete a full itinerary for their vacation, "
        "finding best deals for flights and hotels."
    ),
    name="planning_agent",
    instruction=prompt.PLANNING_AGENT_INSTR,
    tools=[
        AgentTool(agent=flight_search_agent_v2b),
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)


def build_planning_agent() -> Agent:
    """Return the prompt_tuning_v2 planning agent for eval."""
    return planning_agent_v2b
