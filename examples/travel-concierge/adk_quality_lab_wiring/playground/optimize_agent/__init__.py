#!/usr/bin/env python3
"""Flat single-agent variant for adk optimize.

`adk optimize` (GEPA) only rewrites the ROOT agent's instruction. Our normal
playground variants nest the planning agent under a root concierge router,
so GEPA would optimise the routing prompt rather than the flight-search
behaviour we actually want to improve.

This module exposes the planning agent *as* the root agent, giving GEPA
direct access to PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS.

Usage (from examples/travel-concierge/):
  adk optimize adk_quality_lab_wiring/playground/optimize_agent \
    --sampler_config_file_path adk_quality_lab_wiring/playground/eval/sampler_config.json \
    --print_detailed_results
"""

from google.genai.types import GenerateContentConfig

from google.adk.agents import Agent
from travel_concierge import MODEL

from adk_quality_lab_wiring.playground._cash_variant_shared import (
    build_cash_flight_search_agent_full_details,
    build_planning_tools,
)
from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_markdown_table import (
    PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS,
)

# ---------------------------------------------------------------------------
# Build a flat root agent whose instruction IS the planning instruction.
# GEPA will read failures from the eval and rewrite this string directly.
# ---------------------------------------------------------------------------

cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()

root_agent = Agent(
    model=MODEL,
    name="planning_agent",
    description=(
        "Flat root agent for adk optimize. "
        "Exposes the markdown_table planning instruction directly as root "
        "so GEPA can improve it based on hallucinations_v1 failures."
    ),
    instruction=PLANNING_AGENT_INSTR_MINIMAL_RENDER_FLIGHTS,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
    generate_content_config=GenerateContentConfig(temperature=0.1, top_p=0.5),
)

# adk optimize loads __init__.py as the module, then accesses
# agent_module.agent.root_agent — so we need to expose a nested `agent`
# attribute that itself has a root_agent. We do this with a simple namespace.
import types as _types
agent = _types.SimpleNamespace(root_agent=root_agent)

__all__ = ["root_agent", "agent"]
