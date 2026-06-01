#!/usr/bin/env python3
"""Playground-only agent variants for minimal cash-flight rendering experiments.

This keeps production agents unchanged.
"""

from google.adk.agents import Agent
from google.genai.types import GenerateContentConfig

from adk_quality_lab_wiring.playground._cash_variant_shared import (
    build_cash_flight_search_agent_full_details,
    build_planning_tools,
    build_root_agent_minimal_cash,
)
from travel_concierge.shared_libraries.model import MODEL


PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS = """
You are a minimal travel planning assistant focused ONLY on cash flights.

Scope:
- Handle cash flight searches only (SerpAPI-backed cash search flow).
- Do not handle award flights, hotels, alerts, itinerary creation, or booking/payment.

Behavior:
- If user asks for cash flights, search and return results.
- If required fields are missing (origin, destination, date), ask one concise follow-up question.
- If user asks for anything outside cash flight search, briefly say you can only help with cash flight search in this minimal mode.

Output format:
- Render results directly in markdown.
- First line: short summary with number of options found.
- Then render a compact markdown table with columns:
    Date | Airline | Flight # | Departure | Arrival | Duration (min) | Stops | Cabin | Price
- If no flights are found, say so clearly and suggest 1-2 practical adjustments.

Style:
- Keep responses short, clear, and user-friendly.
- Never mention internal tool names or agent implementation details.
"""

cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()


planning_agent_minimal_cash = Agent(
    model=MODEL,
    name="planning_agent_minimal_cash",
    description="Minimal planning variant for cash-flight-only responses.",
    instruction=PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)

root_agent_minimal_cash = build_root_agent_minimal_cash(
    planning_agent_minimal_cash,
    name="root_agent_minimal_cash",
    description="Root variant that routes to minimal cash-flight planning variant.",
)
