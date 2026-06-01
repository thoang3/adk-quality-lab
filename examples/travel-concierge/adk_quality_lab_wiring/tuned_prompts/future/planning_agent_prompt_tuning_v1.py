"""Wired prompt_tuning_v1 planning agent for ADK Quality Lab eval.

VARIANT=prompt_tuning_v1 — first Optimizer iteration.

What changes vs. baseline:
  1. ``FLIGHT_SEARCH_INSTR`` gains verbatim-citation constraints:
     the agent is explicitly told not to abbreviate, round, or mutate values.
  2. ``FLIGHT_SEARCH_INSTR`` gains truncation-disclosure language:
     the agent must open with "Showing X of N — list truncated." when it
     cannot render all results.

What does NOT change vs. baseline:
  - planning_agent instruction (PLANNING_AGENT_INSTR) — identical to upstream
  - FlightsSelection output_schema — identical
  - planning_agent tools list — identical
  - All other sub-agents (hotel, seat, itinerary) — identical

Expected improvement vs. baseline (per §7 target table):
  F1 truncation-disclosure rate:  ~10% → ≥ 75%  (+65pp)
  F2 structured value match:      ~75% → ≥ 93%  (+18pp)

Optimizer run that produced this variant:
  make optimize SURFACE=planning ITERS=20
  (instruction_tuner accepted this candidate at iteration 3)
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

# ---------------------------------------------------------------------------
# Optimizer-tuned instruction: verbatim-citation + truncation-disclosure.
# Targets F1 (Type 2 — Truncation Collapse) and F2 (Type 1 — Value Mutation).
# ---------------------------------------------------------------------------

FLIGHT_SEARCH_INSTR_V1 = """\
You are a flight search agent. Use the search tools to fetch real
flight data, then return the results as a FlightsSelection JSON object.

Steps:
1. If the user asks for a DATE RANGE (e.g. "first week of July", "July 1–7",
   "from July 1 to July 14"):
   Call search_flights_range(origin, destination, start_date, end_date, cabin_class).
   Otherwise call search_flights(origin, destination, outbound_date, cabin_class).
2. Review ALL flights returned by the tool — do not skip or reorder them.
3. Return results as a FlightsSelection JSON.

CRITICAL — Verbatim citation rules (prevents Value Mutation failures):
- Copy every carrier code, flight number, price, departure time, and arrival
  time EXACTLY as it appears in the tool response.
- Do NOT abbreviate carrier names (e.g. keep "UA", not "United").
- Do NOT round or reformat prices (e.g. keep "843.20", not "~$843").
- Do NOT shift times (e.g. keep "14:35", not "2:35pm").
- If a value looks wrong, copy it anyway — do not correct it.

CRITICAL — Truncation disclosure rules (prevents Count Hallucination failures):
- If the tool returns N flights but you can only include M < N in your response
  due to length constraints, the FIRST line of your response MUST be:
  "Showing M of N flights — list truncated."
- Never claim a count larger than the number of flights you actually include.
- Never omit flights silently — always disclose when truncation occurs.

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
# Agent wiring — identical to baseline except FLIGHT_SEARCH_INSTR
# ---------------------------------------------------------------------------

flight_search_agent_v1 = Agent(
    model=MODEL,
    name="flight_search_agent",
    description=(
        "Searches for available flights using real SerpAPI data (fixture-backed). "
        "Returns a FlightsSelection JSON with verbatim values and truncation disclosure."
    ),
    instruction=FLIGHT_SEARCH_INSTR_V1,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    output_schema=types.FlightsSelection,
    output_key="flights",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

planning_agent_v1 = Agent(
    model=MODEL,
    name="planning_agent",
    description=(
        "Helps users with travel planning, complete a full itinerary for their vacation, "
        "finding best deals for flights and hotels."
    ),
    instruction=prompt.PLANNING_AGENT_INSTR,
    tools=[memorize],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
    sub_agents=[
        flight_search_agent_v1,
        hotel_search_agent,
        hotel_room_selection_agent,
        flight_seat_selection_agent,
        itinerary_agent,
    ],
)


# agent_runner imports PLANNING_AGENT_INSTR_V1 and patches planning_agent.instruction.
# The Optimizer-tuned instruction tightens the flight_search_agent sub-prompt, which
# planning_agent forwards to its sub-agent. We surface it here under the expected name.
PLANNING_AGENT_INSTR_V1 = FLIGHT_SEARCH_INSTR_V1


def build_planning_agent() -> Agent:
    """Return the prompt_tuning_v1 planning agent for eval."""
    return planning_agent_v1
