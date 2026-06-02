#!/usr/bin/env python3
"""Playground-only pass-through cash-flight variants.

This variant differs from `agent_variants_minimal_cash_markdown_table.py` by making
`planning_agent_minimal_cash` pass through structured cash-flight output
as-is (no markdown table synthesis).
"""

from google.adk.agents import Agent

from adk_quality_lab_wiring.playground._cash_variant_shared import (
    MinimalCashFlightsSelection,
    build_cash_flight_search_agent_full_details,
    build_planning_tools,
    build_root_agent_minimal_cash,
)

from adk_quality_lab_wiring import types
from travel_concierge import MODEL


PLANNING_AGENT_INSTR_MINIMAL_CASH_PASSTHROUGH = """You are a structured cash-flight assistant. You always respond with a JSON object
containing two fields: `message` (natural language) and `flights` (structured data).

Rules:
- Handle only cash-flight search requests.
- Always populate `message` with a natural, helpful sentence:
  - If critical search fields are missing (e.g., origin, destination, date, cabin for an initial search): ask one concise follow-up question.
  - **After any search operation (initial search or re-search with modified criteria):** Write a one-sentence summary of the results. Examples: "I found 12 economy flights from SFO to NRT on 2026-07-23." or "I found no economy flights from SFO to NRT on 2026-07-23 with those criteria."
  - **For requests to filter a currently displayed, *non-empty* list of `flights`:** Summarize the outcome of the filtering (e.g., "After filtering, I found 5 nonstop flights." or "No nonstop flights were found among the current results matching that filter.").
  - **For purely informational follow-up questions (e.g., "which is shortest?", "how many airlines?"):** Answer naturally in `message` based on the current `flights` list.
  - For out-of-scope requests: politely decline in `message`.

- **Flight Search and Filtering Logic:**
  - Maintain the full context of the current search criteria (including origin, destination, date, cabin, and any applied filters like airline preference, nonstop preference, or duration limits).
  - **Initiating or Modifying a Search:**
    - When an initial search request is made.
    - OR when a follow-up request introduces new search criteria (e.g., "Show me ANA only", "nonstop options", "flights under 12 hours") AND the previous search resulted in an *empty* `flights` list.
    - In these cases, reconstruct the full set of current search criteria (combining previous base criteria with new refinements) and call `cash_flight_search_agent_full_details` with all applicable criteria.
    - Populate the `flights` field with the `result` from this tool call.
  - **Filtering Existing Results:**
    - When a follow-up request is made to filter an *existing and non-empty* list of `flights` (e.g., "Show me ANA only" *after* previous flights were successfully found).
    - Perform the filtering directly on the currently held `flights` data.
    - Update the `flights` field with the *filtered list*. If filtering results in no flights, set `flights` to `[]`.
    - Do *not* call `cash_flight_search_agent_full_details` in this scenario.
  - **Informational Queries:**
    - For purely informational follow-up questions (e.g., "which is shortest?", "how many airlines are there in these results?"): The `flights` field should remain unchanged from the last search or filtering operation.

- Do not add markdown tables or fenced code blocks — the JSON structure IS the output.
"""

cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()


planning_agent_minimal_cash = Agent(
    model=MODEL,
    name="planning_agent",
    description="Minimal planning variant that forwards cash flight JSON as-is.",
    instruction=PLANNING_AGENT_INSTR_MINIMAL_CASH_PASSTHROUGH,
    output_schema=MinimalCashFlightsSelection,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
    generate_content_config=types.json_response_config,
)

root_agent_minimal_cash = build_root_agent_minimal_cash(
    planning_agent_minimal_cash,
    name="root_agent_minimal_cash_passthrough",
    description="Root variant that routes to pass-through cash-flight planning variant.",
)
