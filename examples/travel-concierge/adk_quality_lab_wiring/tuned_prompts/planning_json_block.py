"""Condition B — JSON code-fence synthesis (paper §3, Table 1).

VARIANT=json_block  →  paper's Condition B.

What this is:
  flight_search_agent receives the full SerpAPI flight list and synthesizes it
  into a FREE-FORM JSON CODE FENCE — no output_schema, no json_response_config,
  but the instruction explicitly asks for a JSON code block. This is the worst
  synthesis path on large payloads: JSON delimiters + whitespace inflate token
  count, causing deterministic streaming-budget disconnect (Type 4 — Connection
  Collapse) before the response completes on queries with ≥ 80 ground-truth
  flights.

Expected behaviour vs. other variants:
  - Small payloads (≤ 20 flights): near-identical to Conditions A and C.
  - Large payloads (≥ 80 flights): ServerDisconnectedError after ~125–133 s,
    zero output → F1 = 0.00, F2 = 0.00.
  - Avg output tokens: ~2,104 (highest of all synthesis conditions).

Paper reference: AGENTWILD Table 1, Condition B — JSON block, field fidelity 0.87,
fidelity ≥ 0.95: 50%, avg latency 20.9 s, avg output tokens 2,104, 2 failures.
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

# Condition B: append code-fence formatting requirement to the base planning instruction.
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

from tools.fixture_flight_search import search_flights, search_flights_range  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Condition B instruction — JSON code fence, no schema enforcement.
# Token-heavy format → connection collapse on tail payloads.
# ---------------------------------------------------------------------------

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
       },
       ...
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

# ---------------------------------------------------------------------------
# flight_search_agent_json_block — NO output_schema, NO json_response_config.
# Asks for explicit JSON code fence. Paper Condition B.
# ---------------------------------------------------------------------------

flight_search_agent_json_block = Agent(
    model=MODEL,
    name="flight_search_agent",
    description="Searches for available flights and returns results as a JSON code block.",
    instruction=FLIGHT_SEARCH_INSTR_JSON_BLOCK,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    # Deliberately NO output_schema and NO json_response_config — Condition B.
)

# ---------------------------------------------------------------------------
# planning_agent_json_block: wraps flight_search_agent_json_block.
# ---------------------------------------------------------------------------

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
