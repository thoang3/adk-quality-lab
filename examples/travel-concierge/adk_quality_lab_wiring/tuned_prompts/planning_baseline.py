"""Wired baseline planning agent for ADK Quality Lab eval.

This module creates the VARIANT=baseline agent: vanilla upstream planning
logic + the minimal SerpAPI wiring needed to make the eval meaningful.

What changes vs. the raw vendored agent:
  1. `flight_search_agent` gains one tool: `search_flights` (fixture-backed)
  2. `FLIGHT_SEARCH_INSTR` is updated to instruct use of the tool

What does NOT change vs. upstream:
  - planning_agent instruction (PLANNING_AGENT_INSTR) — identical
  - FlightsSelection output_schema — identical
  - planning_agent tools list — identical
  - All other sub-agents (hotel, seat, itinerary) — identical

Why this is still a valid "baseline":
  The interesting failures (F1 count hallucination, F2 value mutation) happen
  during LLM *synthesis* — when the model renders real search results into its
  response. By feeding real data in, we measure synthesis faithfulness.
  Without this wiring, the eval measures pure hallucination from weights, which
  is neither interesting nor fixable by prompt tuning.

Intentional omissions (these are what later variants fix):
  - No truncation-disclosure instruction (added in prompt_tuning_v1)
  - No verbatim-citation constraint (added in prompt_tuning_v1)
  - No JSON schema output enforcement (added in structured_output)
"""

from __future__ import annotations

import copy

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL  # type: ignore[import-untyped]
from travel_concierge.shared_libraries import types  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning import prompt  # type: ignore[import-untyped]
from travel_concierge.tools.memory import memorize  # type: ignore[import-untyped]

# Import the vanilla sub-agents we reuse unchanged
from travel_concierge.sub_agents.planning.agent import (  # type: ignore[import-untyped]
    hotel_room_selection_agent,
    hotel_search_agent,
    flight_seat_selection_agent,
    itinerary_agent,
)

from tools.fixture_flight_search import search_flights  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Minimal instruction update: instruct the agent to use the search tool.
# Intentionally omits disclosure language and verbatim-citation constraints
# (those are added by the Optimizer in prompt_tuning_v1).
# ---------------------------------------------------------------------------

FLIGHT_SEARCH_INSTR_BASELINE = """\
You are a flight search agent. Use the `search_flights` tool to fetch real
flight data, then return the results as a FlightsSelection JSON object.

Steps:
1. Call search_flights(origin, destination, outbound_date, cabin_class) using
   the route details from the user query.
2. Review the flights returned by the tool.
3. Return ALL flights as a FlightsSelection JSON — do not omit any flight.

Do not invent or modify flight details. Use only what the tool returns.

Current context:
  origin:      {origin}
  destination: {destination}
  Current time: {_time}

User profile:
  <user_profile>
  {user_profile}
  </user_profile>
"""

# ---------------------------------------------------------------------------
# flight_search_agent: vanilla agent + search_flights tool wired in.
# All other fields (output_schema, generate_content_config) are unchanged.
# ---------------------------------------------------------------------------

flight_search_agent_baseline = Agent(
    model=MODEL,
    name="flight_search_agent",
    description="Help users find best flight deals",
    instruction=FLIGHT_SEARCH_INSTR_BASELINE,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_schema=types.FlightsSelection,
    output_key="flight",
    generate_content_config=types.json_response_config,
    tools=[FunctionTool(func=search_flights)],
)

# ---------------------------------------------------------------------------
# planning_agent_baseline: vanilla planning agent with wired flight search.
# Instruction is the upstream PLANNING_AGENT_INSTR — identical to vendored.
# ---------------------------------------------------------------------------

planning_agent_baseline = Agent(
    model=MODEL,
    description="Helps users with travel planning, complete a full itinerary for their vacation, "
    "finding best deals for flights and hotels.",
    name="planning_agent",
    instruction=prompt.PLANNING_AGENT_INSTR,
    tools=[
        AgentTool(agent=flight_search_agent_baseline),
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)
