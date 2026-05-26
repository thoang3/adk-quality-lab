# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Condition D — lazy-load / SSE-inject architecture (paper §3, Table 1).

VARIANT=arch_fix  →  paper's Condition D.

What this is:
  flight_search_agent stores the FULL raw fixture into session state via the
  `memorize` tool (key: 'flights'), then returns only a tiny natural-language
  summary (~42 tokens).  planning_agent calls `get_flight_context` on demand
  to pull individual flights from session state — the LLM never synthesises the
  full flight list inline.

  This mirrors AGENTWILD's SSE-injection path (Condition D): structured data
  bypasses the synthesis LLM entirely, so truncation collapse and value mutation
  are eliminated.

Expected behaviour vs. other variants:
  - F1 (recall):   ~0.990 — almost no dropped flights
  - F2 (fidelity): ~0.350+ — very low mutation rate
  - Latency:        low — flight_search_agent returns ~42 tokens instead of ~2 000

Paper reference: AGENTWILD Table 1, Condition D — SSE inject, field fidelity 0.97,
fidelity ≥ 0.95: 90%, avg latency 6.2 s, avg output tokens 42.
"""

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning import prompt  # type: ignore[import-untyped]
from travel_concierge.tools.search import CashFlightSummary  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning.agent import (  # type: ignore[import-untyped]
    flight_seat_selection_agent,
    hotel_room_selection_agent,
    hotel_search_agent,
    itinerary_agent,
)
from travel_concierge.tools.flights import get_flight_context  # type: ignore[import-untyped]
from travel_concierge.tools.memory import memorize  # type: ignore[import-untyped]

from tools.fixture_flight_search import search_flights, search_flights_range  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Condition D: flight_search_agent stores full data → returns lean summary
# ---------------------------------------------------------------------------

FLIGHT_SEARCH_INSTR_LAZY = """\
You are a flight search agent. Search for available flights and return a lean
count summary — the full raw data is stored in session state and planning_agent
will call get_flight_context to retrieve the actual flights on demand.

Steps:
1. If the user asks for a DATE RANGE (e.g. "first week of July", "July 1–7"):
   Call search_flights_range(origin, destination, start_date, end_date, cabin_class).
   Otherwise call search_flights(origin, destination, outbound_date, cabin_class).
2. From the tool result, set:
   total_found  → the "total_count" value from the tool response (do NOT count yourself)
   search_params → short label e.g. "ORD→NRT, Economy, Jul 6"
   Do NOT enumerate individual flights.

Current context:
  origin:      {origin}
  destination: {destination}
  Current time: {_time}

User profile:
  <user_profile>
  {user_profile}
  </user_profile>
"""

flight_search_agent_lazy = Agent(
    model=MODEL,
    name="flight_search_agent",
    description=(
        "Searches for available flights and returns a lean count summary. "
        "Full raw data is stored in session state under search_results_cash — "
        "call get_flight_context to retrieve actual flight details."
    ),
    instruction=FLIGHT_SEARCH_INSTR_LAZY,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    output_schema=CashFlightSummary,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    generate_content_config=GenerateContentConfig(response_mime_type="application/json"),
)

# ---------------------------------------------------------------------------
# planning_agent_v2 — Condition D: uses lazy-load get_flight_context
# ---------------------------------------------------------------------------

PLANNING_AGENT_INSTR_ARCH_FIX = prompt.PLANNING_AGENT_INSTR + """

FLIGHT DATA — TWO-TOOL PROTOCOL:

1. INITIAL SEARCH: Delegate to flight_search_agent ONCE to fetch and store flights.
   flight_search_agent returns a CashFlightSummary with `total_found` and `search_params`.
   You MUST begin your response with exactly: "I found N flights for PARAMS." where N is the total_found value and PARAMS is the search_params value from the flight_search_agent result.
   Then immediately call get_flight_context() with NO filters to retrieve and list the flights.

2. FOLLOW-UP FILTERING: For ANY follow-up that filters the flight list (e.g.
   "show nonstop only", "under $1000", "morning departures", "which is cheapest",
   "show me UA flights") — do NOT call flight_search_agent again.
   Call get_flight_context() with the appropriate filter parameters:
     - num_stops=0                    for nonstop only
     - max_price=N                    for price cap
     - airline="UA"                   for a specific carrier
     - departure_after/before="HH:MM" for time windows
     - max_duration_minutes=N         for duration cap
   get_flight_context reads the full raw flight list stored in session state
   and filters server-side — no LLM synthesis of large lists required.

Never re-call flight_search_agent for follow-up filtering. Always use get_flight_context.
"""

planning_agent_v2 = Agent(
    model=MODEL,
    description=(
        "Helps users with travel planning, complete a full itinerary for their vacation, "
        "finding best deals for flights and hotels."
    ),
    name="planning_agent",
    instruction=PLANNING_AGENT_INSTR_ARCH_FIX,
    tools=[
        AgentTool(agent=flight_search_agent_lazy),
        FunctionTool(get_flight_context),  # reads search_results_cash — pre-loaded by harness
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)
