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

"""Tuned planning agent — architectural variant (v2).

Replaces the vanilla flight_search_agent (full FlightsSelection output) with
cash_flight_search_agent (CashFlightSummary output). This prevents the LLM
from receiving 100+ flights in context, eliminating truncation collapse (F1)
and reducing value mutation (F2) because the agent no longer synthesises a
large flight list inline.

This module is NOT used for the baseline eval. It is activated by:
    make eval VARIANT=tuned_v2
or wired in by instruction_tuner.py after prompt-only tuning plateaus.
"""

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL
from travel_concierge.shared_libraries import types
from travel_concierge.sub_agents.planning import prompt
from travel_concierge.sub_agents.planning.agent import (
    flight_seat_selection_agent,
    hotel_room_selection_agent,
    hotel_search_agent,
    itinerary_agent,
)
from travel_concierge.tools.memory import memorize
from travel_concierge.tools.search import (
    CashFlightSummary,
    search_cash_flights_with_count,
)

# ---------------------------------------------------------------------------
# Cash flight search — lean summary output (eliminates truncation collapse)
# ---------------------------------------------------------------------------

CASH_FLIGHT_SEARCH_INSTR = """Generate search results for flights from origin to destination inferred from user query.
- Ask for any details you don't know, like origin and destination.
- You must generate a non-empty JSON response if the user provides origin and destination.

⭐ SUMMARY OUTPUT — CRITICAL:
After calling the search tool, return a lean summary ONLY:
1. Set `total_found` = the `total_count` value from the tool response exactly.
   Do NOT count flights yourself.
2. Set `search_params` = short human-readable label, e.g. "SFO→LHR, Economy".
Do NOT enumerate individual flights — planning_agent loads details on demand.

SEARCH FILTERS — extract from the user query:
- **cabin_class**: "Economy", "Premium Economy", "Business", or "First"
- **max_price**: maximum cash price (e.g. "under $1000")
- **preferred_airlines**: list of airline names or codes
- **max_stops**: 0=nonstop, 1=up to 1 stop, 2=up to 2 stops, omit=any

Current user:
  <user_profile>
  {user_profile?}
  </user_profile>

Current time: {_time?}
Origin: {origin?}  Destination: {destination?}
"""

search_cash_flights_tool = FunctionTool(func=search_cash_flights_with_count)

cash_flight_search_agent = Agent(
    model=MODEL,
    name="cash_flight_search_agent",
    description="Find best cash flight deals and return a lean count summary",
    instruction=CASH_FLIGHT_SEARCH_INSTR,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_schema=CashFlightSummary,
    tools=[search_cash_flights_tool],
    generate_content_config=types.json_response_config,
)

# ---------------------------------------------------------------------------
# Tuned planning agent (v2) — uses cash_flight_search_agent
# ---------------------------------------------------------------------------

planning_agent_v2 = Agent(
    model=MODEL,
    description="Travel planning agent — architectural variant with lean flight summaries.",
    name="planning_agent",
    instruction=prompt.PLANNING_AGENT_INSTR,
    tools=[
        AgentTool(agent=cash_flight_search_agent),
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)
