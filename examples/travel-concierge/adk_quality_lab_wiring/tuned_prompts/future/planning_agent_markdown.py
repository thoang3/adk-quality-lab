"""Condition A — Markdown synthesis (paper §3, Table 1).

VARIANT=markdown  →  paper's Condition A.

What this is:
  flight_search_agent receives the full SerpAPI flight list and synthesizes it
  into a FREE-FORM MARKDOWN TABLE — no output_schema, no json_response_config,
  no citation constraints. This is the most naive synthesis path and the one
  that exhibits silent truncation with completeness mismatch on large payloads
  (Type 2 — Truncation Collapse in the AGENTWILD taxonomy).

Expected behaviour vs. other variants:
  - Small payloads (≤ 20 flights): near-identical to baseline (Condition C).
  - Large payloads (≥ 80 flights): agent renders ~20 rows, claims full count →
    F1 count-mismatch score = 0.00 (strict policy, see AGENTWILD §Scoring).
  - Field fidelity: ~0.87–0.89 on correctly-rendered rows (value mutation).

This variant is the *regression reference* for the AGENTWILD replication:
  markdown (A) → baseline/response_schema (C) → arch_fix (D)
should show the full improvement arc.

Paper reference: AGENTWILD Table 1, Condition A — Markdown, field fidelity 0.89,
fidelity ≥ 0.95: 52%, avg latency 11.4 s, avg output tokens 1,259.
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
# Condition A instruction — no citation rules, no disclosure, no schema.
# The LLM decides how many rows to render and what to say about the count.
# ---------------------------------------------------------------------------

FLIGHT_SEARCH_INSTR_MARKDOWN = """\
You are a flight search agent. Use the appropriate search tool, then present ALL results as a markdown table.

Tool selection:
- For a SINGLE departure date: call search_flights(origin, destination, outbound_date, cabin_class)
- For a DATE RANGE (multiple days): call search_flights_range(origin, destination, start_date, end_date, cabin_class)

Steps:
1. Choose the correct tool based on whether the query is for one date or a range.
2. Present ALL results as a markdown table with columns:
   Date | Airline | Flight # | Departure | Arrival | Stops | Price
3. Include every flight returned by the tool — do not skip any.

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
# flight_search_agent_markdown — NO output_schema, NO json_response_config.
# Free-form markdown synthesis. Paper Condition A.
# ---------------------------------------------------------------------------

flight_search_agent_markdown = Agent(
    model=MODEL,
    name="flight_search_agent",
    description="Searches for available flights and returns results as a markdown table.",
    instruction=FLIGHT_SEARCH_INSTR_MARKDOWN,
    tools=[FunctionTool(search_flights), FunctionTool(search_flights_range)],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    # Deliberately NO output_schema and NO json_response_config — Condition A.
)

# ---------------------------------------------------------------------------
# planning_agent_markdown: wraps flight_search_agent_markdown.
# planning_agent itself is also free-form (no schema constraint).
# ---------------------------------------------------------------------------

planning_agent_markdown = Agent(
    model=MODEL,
    description=(
        "Helps users with travel planning, complete a full itinerary for their vacation, "
        "finding best deals for flights and hotels."
    ),
    name="planning_agent",
    instruction=prompt.PLANNING_AGENT_INSTR,
    tools=[
        AgentTool(agent=flight_search_agent_markdown),
        AgentTool(agent=flight_seat_selection_agent),
        AgentTool(agent=hotel_search_agent),
        AgentTool(agent=hotel_room_selection_agent),
        AgentTool(agent=itinerary_agent),
        memorize,
    ],
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)
