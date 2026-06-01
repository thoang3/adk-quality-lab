"""Condition B — JSON code-fence synthesis (paper §3, Table 1).

VARIANT=json_block  →  paper's Condition B.

This variant is intentionally deferred from the default audit path due to its
token-heavy output behavior on large payloads, but remains importable for
replication completeness.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning import prompt  # type: ignore[import-untyped]
from travel_concierge.tools.memory import memorize  # type: ignore[import-untyped]
from travel_concierge.sub_agents.planning.agent import (  # type: ignore[import-untyped]
    flight_seat_selection_agent,
    hotel_room_selection_agent,
    hotel_search_agent,
    itinerary_agent,
)

from tools.fixture_flight_search import search_flights, search_flights_range  # type: ignore[import-untyped]

PLANNING_AGENT_INSTR_JSON_BLOCK = (
    prompt.PLANNING_AGENT_INSTR
    + """

## Flight Result Formatting (REQUIRED)
When presenting flight search results to the user, you MUST format them as a
JSON code block (```json ... ```) with this exact structure:
```json
{
  "flights": [
    {
      "airline": "<carrier>",
      "flight_number": "<code>",
      "departure": "<YYYY-MM-DD HH:MM>",
      "arrival": "<YYYY-MM-DD HH:MM>",
      "stops": <int>,
      "price_usd": <int>
    }
  ]
}
```
Do NOT use a table or bullet list for flight results. Use the JSON code block.
"""
)

FLIGHT_SEARCH_INSTR_JSON_BLOCK = """\
You are a flight search agent. Use the appropriate search tool, then return ALL results as a JSON array inside a code fence.

Tool selection:
- For a SINGLE departure date: call search_flights(origin, destination, outbound_date, cabin_class)
- For a DATE RANGE (multiple days): call search_flights_range(origin, destination, start_date, end_date, cabin_class)

Steps:
1. Choose the correct tool based on whether the query is for one date or a range.
2. Return ALL flights in a JSON code fence (```json ... ```) with this structure:
   {
     "total_count": <number>,
     "flights": [
       {
         "airline": "<carrier name>",
         "flight_number": "<code>",
         "departure": "<HH:MM>",
         "arrival": "<HH:MM>",
         "stops": <number>,
         "price_usd": <number>
       }
     ]
   }
3. Every flight returned by the tool must appear in the array — do not omit any.

Current context:
  origin:      {origin}
  destination: {destination}
  Current time: {_time}

User profile:
  <user_profile>
  {user_profile}
  </user_profile>
"""

flight_search_agent_json_block = Agent(
    model=MODEL,
    name="flight_search_agent",
    description="Searches for available flights and returns results as a JSON code block.",
    instruction=FLIGHT_SEARCH_INSTR_JSON_BLOCK,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

planning_agent_json_block = Agent(
    model=MODEL,
    description=(
        "Helps users with travel planning, complete a full itinerary for their vacation, "
        "finding best deals for flights and hotels."
    ),
    name="planning_agent",
    instruction=PLANNING_AGENT_INSTR_JSON_BLOCK,
    tools=[
        AgentTool(agent=flight_search_agent_json_block),
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)
