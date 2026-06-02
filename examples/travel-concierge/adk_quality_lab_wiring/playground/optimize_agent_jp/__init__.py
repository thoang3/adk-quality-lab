#!/usr/bin/env python3
"""Flat single-agent variant for adk optimize — json_passthrough planning variant.

Mirrors optimize_agent/__init__.py but targets PLANNING_AGENT_INSTR_MINIMAL_CASH_PASSTHROUGH
so GEPA rewrites the json_passthrough planning instruction (not the markdown_table one).

Usage (from examples/travel-concierge/):
  adk optimize adk_quality_lab_wiring/playground/optimize_agent_jp \
    --sampler_config_file_path adk_quality_lab_wiring/playground/eval/sampler_config_jp.json \
    --print_detailed_results
"""

import types as _types

from google.adk.agents import Agent
from google.genai.types import GenerateContentConfig

from travel_concierge import MODEL

from adk_quality_lab_wiring.playground._cash_variant_shared import (
    MinimalCashFlightsSelection,
    build_cash_flight_search_agent_full_details,
    build_planning_tools,
)
from adk_quality_lab_wiring import types as _adk_types
from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_json_passthrough import (
    PLANNING_AGENT_INSTR_MINIMAL_CASH_PASSTHROUGH,
)

# ---------------------------------------------------------------------------
# Flat root agent whose instruction IS the json_passthrough planning instruction.
# GEPA rewrites this string based on hallucinations_v1 failures.
# output_schema is kept so the structured JSON contract is preserved.
# ---------------------------------------------------------------------------

cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()

root_agent = Agent(
    model=MODEL,
    name="planning_agent",
    description=(
        "Flat root agent for adk optimize — json_passthrough variant. "
        "Exposes the json_passthrough planning instruction directly as root "
        "so GEPA can improve it based on hallucinations_v1 failures."
    ),
    instruction=PLANNING_AGENT_INSTR_MINIMAL_CASH_PASSTHROUGH,
    output_schema=MinimalCashFlightsSelection,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
    generate_content_config=_adk_types.json_response_config,
)

# adk optimize accesses agent_module.agent.root_agent
agent = _types.SimpleNamespace(root_agent=root_agent)

__all__ = ["root_agent", "agent"]
