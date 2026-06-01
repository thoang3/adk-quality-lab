# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for travel_concierge/tools/flights.py."""

import sys
from pathlib import Path

from travel_concierge.tools.flights import _parse_stops_string


_WIRING_DIR = Path(__file__).resolve().parents[2] / "adk_quality_lab_wiring"
if str(_WIRING_DIR) not in sys.path:
    sys.path.insert(0, str(_WIRING_DIR))


# ---------------------------------------------------------------------------
# _parse_stops_string helper
# ---------------------------------------------------------------------------


def test_parse_stops_nonstop_string():
    assert _parse_stops_string("Nonstop") == 0


def test_parse_stops_nonstop_case_insensitive():
    assert _parse_stops_string("NONSTOP") == 0


def test_parse_stops_one_stop_string():
    assert _parse_stops_string("1 stop(s)") == 1


def test_parse_stops_two_stops_string():
    assert _parse_stops_string("2 stop(s)") == 2


def test_parse_stops_integer_passthrough():
    assert _parse_stops_string(0) == 0
    assert _parse_stops_string(1) == 1


def test_parse_stops_empty_returns_minus_one():
    assert _parse_stops_string("") == -1
    assert _parse_stops_string(None) == -1


def test_parse_stops_invalid_returns_minus_one():
    assert _parse_stops_string("unknown") == -1


# ---------------------------------------------------------------------------
# CashFlightSummary schema
# ---------------------------------------------------------------------------


def test_cash_flight_summary_schema():
    """CashFlightSummary schema check."""
    from travel_concierge.tools.search import CashFlightSummary

    summary = CashFlightSummary(total_found=12, search_params="SFO→NRT, Economy")
    assert summary.total_found == 12
    assert summary.search_params == "SFO→NRT, Economy"


def test_cash_flight_summary_defaults():
    from travel_concierge.tools.search import CashFlightSummary

    summary = CashFlightSummary(total_found=0)
    assert summary.search_params == ""


# ---------------------------------------------------------------------------
# cash_flight_search_agent uses CashFlightSummary (not CashFlightsSelection)
# ---------------------------------------------------------------------------


def test_cash_flight_search_agent_uses_cash_flight_summary():
    from tuned_prompts.planning_agent_arch_fix import flight_search_agent_lazy
    from travel_concierge.tools.search import CashFlightSummary

    assert flight_search_agent_lazy.output_schema is CashFlightSummary


# ---------------------------------------------------------------------------
# v2 planning agent wiring covers cash format
# ---------------------------------------------------------------------------


def test_planning_prompt_cash_table_format():
    from tuned_prompts.planning_agent_arch_fix import FLIGHT_SEARCH_INSTR_LAZY

    assert "summary" in FLIGHT_SEARCH_INSTR_LAZY.lower()


def test_cash_flight_search_instr_has_summary_rule():
    from tuned_prompts.planning_agent_arch_fix import FLIGHT_SEARCH_INSTR_LAZY

    assert "total_found" in FLIGHT_SEARCH_INSTR_LAZY
    assert "search_params" in FLIGHT_SEARCH_INSTR_LAZY
