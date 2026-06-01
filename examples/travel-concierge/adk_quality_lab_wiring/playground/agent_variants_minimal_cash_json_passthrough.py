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
  - If fields are missing: ask one concise follow-up question.
  - After a search: write a one-sentence summary (e.g. "I found 12 economy flights from SFO to NRT on 2026-07-23.").
  - For follow-up questions (e.g. "which is shortest?"): answer naturally in `message`; leave `flights` as the previously returned list or empty.
  - For out-of-scope requests: politely decline in `message`.
- When all search fields are available, call `cash_flight_search_agent_full_details` and populate `flights` with the results.
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
