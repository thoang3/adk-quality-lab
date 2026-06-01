#!/usr/bin/env python3
"""Playground-only JSON code-block cash-flight variant.

This variant differs from `agent_variants_minimal_cash_markdown_table.py` by making
`planning_agent_minimal_cash` present results as a JSON code block synthesized
by the planning agent (Condition B-like behavior).
"""

from google.adk.agents import Agent

from adk_quality_lab_wiring.playground._cash_variant_shared import (
  build_cash_flight_search_agent_full_details,
  build_planning_tools,
  build_root_agent_minimal_cash,
)

from travel_concierge.shared_libraries import types
from travel_concierge.shared_libraries.model import MODEL


PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK = """You are a minimal travel planning assistant focused ONLY on cash flights.

Rules:
- Handle only cash-flight search requests.
- If required fields are missing, ask one concise follow-up question.
- When fields are available, call `cash_flight_search_agent_full_details`.

Output format:
- Start with a short one-sentence summary (e.g., "I found 8 cash flight options for you:").
- Then emit exactly one JSON code block using markdown fences:
  ```json
  {
    "flights": [ ... ]
  }
  ```
- Include ALL flights returned by the search. Do not filter, curate, or truncate.
- For each flight object, include exactly these fields in exactly this order:
  1) date
  2) airline
  3) flight_number
  4) depart_time
  5) arrive_time
  6) duration_minutes
  7) stops
  8) travel_class
  9) price
- Do not include any additional fields.
- Keep original field values unchanged.
- Do not output markdown tables.
"""

cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()


planning_agent_minimal_cash = Agent(
    model=MODEL,
    name="planning_agent_minimal_cash_json_code_block",
    description="Minimal planning variant that renders cash flights in a JSON code block.",
    instruction=PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
    generate_content_config=types.markdown_default_config,
)

root_agent_minimal_cash = build_root_agent_minimal_cash(
    planning_agent_minimal_cash,
    name="root_agent_minimal_cash_json_code_block",
    description="Root variant that routes to JSON code-block cash-flight planning variant.",
)
