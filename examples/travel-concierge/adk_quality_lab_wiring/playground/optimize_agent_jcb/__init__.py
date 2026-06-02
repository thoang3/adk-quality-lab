#!/usr/bin/env python3
"""Flat agent for GEPA optimization — json_code_block planning variant.

This module creates a single-agent app that GEPA can optimize by evolving
the instruction text. It preserves the json_code_block variant's behavior:
the agent synthesizes a JSON code block (no output_schema enforcement).

After optimization, copy the evolved instruction back into:
  agent_variants_minimal_cash_json_code_block.py → PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK
"""

import types as _types

from google.adk.agents import Agent

from adk_quality_lab_wiring.playground._cash_variant_shared import (
  build_cash_flight_search_agent_full_details,
  build_planning_tools,
)

from travel_concierge import MODEL


# Import the baseline instruction to be optimized
from adk_quality_lab_wiring.playground.agent_variants_minimal_cash_json_code_block import (
  PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK,
)


cash_flight_search_agent_full_details = build_cash_flight_search_agent_full_details()


# Flat agent (no delegation) — GEPA optimizes the instruction
root_agent = Agent(
    model=MODEL,
    name="root_agent",
    description="Flat agent for GEPA optimization of json_code_block planning instruction.",
    instruction=PLANNING_AGENT_INSTR_MINIMAL_CASH_JSON_CODE_BLOCK,
    tools=build_planning_tools(cash_flight_search_agent_full_details),
)


# ADK CLI expects `agent.root_agent` attribute
agent = _types.SimpleNamespace(root_agent=root_agent)
