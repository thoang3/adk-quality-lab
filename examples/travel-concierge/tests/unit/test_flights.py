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

from unittest.mock import MagicMock

from travel_concierge.tools.flights import (
    _parse_points,
    _parse_stops_string,
    get_flight_context,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AWARD_FLIGHTS = [
    {
        "flight_number": "QR701",
        "airline": ["QR"],
        "mileage_cost": "69900",
        "stops": 1,
        "travel_class": "Economy",
        "departure": "SFO",
        "arrival": "DOH",
    },
    {
        "flight_number": "AF276",
        "airline": ["AF"],
        "mileage_cost": "49500",
        "stops": 0,
        "travel_class": "Economy",
        "departure": "SFO",
        "arrival": "NRT",
    },
    {
        "flight_number": "AS007",
        "airline": ["AS"],
        "mileage_cost": "35000",
        "stops": 0,
        "travel_class": "Business",
        "departure": "SFO",
        "arrival": "NRT",
    },
]

CASH_FLIGHTS_BY_CABIN = {
    "Economy": [
        {
            "flight_number": "UA837",
            "airline": "United Airlines",
            "price": "$450",
            "stops": "Nonstop",
            "travel_class": "Economy",
        }
    ],
    "Business": [
        {
            "flight_number": "NH175",
            "airline": "All Nippon Airways",
            "price": "$3200",
            "stops": "Nonstop",
            "travel_class": "Business",
        }
    ],
}

# Cash flights with realistic string stops for num_stops filter tests
CASH_FLIGHTS_MIXED_STOPS = {
    "Economy": [
        {
            "flight_number": "UA837",
            "airline": "United Airlines",
            "price": "$450",
            "stops": "Nonstop",
            "travel_class": "Economy",
        },
        {
            "flight_number": "DL200",
            "airline": "Delta Air Lines",
            "price": "$380",
            "stops": "1 stop(s)",
            "travel_class": "Economy",
        },
        {
            "flight_number": "AA300",
            "airline": "American Airlines",
            "price": "$360",
            "stops": "2 stop(s)",
            "travel_class": "Economy",
        },
    ],
}


def _make_tool_context(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    return ctx


def _award_state() -> dict:
    return {
        "last_award_search": {
            "results": list(AWARD_FLIGHTS),
            "route": "SFO-NRT",
            "date": "2026-07-20",
            "cabin_class": "economy",
        }
    }


def _cash_state() -> dict:
    return {
        "last_cash_search": {
            "results": dict(CASH_FLIGHTS_BY_CABIN),
            "route": "SFO-NRT",
            "cabin_class": "economy",
        }
    }


# ---------------------------------------------------------------------------
# Basic loading
# ---------------------------------------------------------------------------


def test_returns_empty_when_no_tool_context():
    assert get_flight_context(tool_context=None) == []


def test_returns_empty_when_state_is_none():
    ctx = MagicMock()
    ctx.state = None
    assert get_flight_context(tool_context=ctx) == []


def test_returns_empty_when_no_search_in_state():
    ctx = _make_tool_context({})
    assert get_flight_context(search_type="award", tool_context=ctx) == []


def test_award_loads_from_last_award_search():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", tool_context=ctx)
    assert len(result) == 3


def test_cash_loads_from_last_cash_search_and_flattens_cabins():
    ctx = _make_tool_context(_cash_state())
    result = get_flight_context(search_type="cash", tool_context=ctx)
    assert len(result) == 2  # 1 Economy + 1 Business


# ---------------------------------------------------------------------------
# No fallback between types
# ---------------------------------------------------------------------------


def test_award_does_not_fall_back_to_cash():
    """If last_award_search is absent but last_cash_search exists, return []."""
    ctx = _make_tool_context(_cash_state())
    result = get_flight_context(search_type="award", tool_context=ctx)
    assert result == []


def test_cash_does_not_fall_back_to_award():
    """If last_cash_search is absent but last_award_search exists, return []."""
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="cash", tool_context=ctx)
    assert result == []


# ---------------------------------------------------------------------------
# flight_number filter
# ---------------------------------------------------------------------------


def test_filter_by_flight_number_exact():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", flight_number="QR701", tool_context=ctx
    )
    assert len(result) == 1
    assert result[0]["flight_number"] == "QR701"


def test_filter_by_flight_number_case_insensitive():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", flight_number="qr701", tool_context=ctx
    )
    assert len(result) == 1


def test_filter_by_flight_number_no_match_returns_empty():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", flight_number="XX999", tool_context=ctx
    )
    assert result == []


# ---------------------------------------------------------------------------
# airline filter
# ---------------------------------------------------------------------------


def test_filter_by_airline_code():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", airline="AF", tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "AF276"


def test_filter_by_airline_via_flight_number_prefix():
    """Airline "AS" should match AS007 even if "airline" list only has ["AS"]."""
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", airline="AS", tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "AS007"


# ---------------------------------------------------------------------------
# num_stops filter
# ---------------------------------------------------------------------------


def test_filter_nonstop():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", num_stops=0, tool_context=ctx)
    assert len(result) == 2
    assert all(f["stops"] == 0 for f in result)


def test_filter_one_stop():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", num_stops=1, tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "QR701"


# ---------------------------------------------------------------------------
# max_points filter
# ---------------------------------------------------------------------------


def test_filter_max_points():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", max_points=50000, tool_context=ctx)
    # AF276=49500, AS007=35000 qualify; QR701=69900 does not
    assert len(result) == 2
    assert all(int(f["mileage_cost"]) <= 50000 for f in result)


# ---------------------------------------------------------------------------
# cabin_class filter
# ---------------------------------------------------------------------------


def test_filter_cabin_class():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", cabin_class="Business", tool_context=ctx
    )
    assert len(result) == 1
    assert result[0]["flight_number"] == "AS007"


def test_filter_cabin_class_case_insensitive():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", cabin_class="business", tool_context=ctx
    )
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Combined filters (AND logic)
# ---------------------------------------------------------------------------


def test_combined_filters_airline_and_nonstop():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", airline="QR", num_stops=0, tool_context=ctx
    )
    # QR701 has 1 stop → excluded
    assert result == []


def test_combined_filters_nonstop_and_max_points():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(
        search_type="award", num_stops=0, max_points=40000, tool_context=ctx
    )
    # AF276=49500 nonstop but over budget; AS007=35000 nonstop and in budget
    assert len(result) == 1
    assert result[0]["flight_number"] == "AS007"


# ---------------------------------------------------------------------------
# No filters → all flights returned (no implicit cap)
# ---------------------------------------------------------------------------


def test_no_filters_returns_all():
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="award", tool_context=ctx)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# API safety: no row/index parameter
# ---------------------------------------------------------------------------


def test_no_row_or_index_parameter():
    import inspect

    sig = inspect.signature(get_flight_context)
    param_names = set(sig.parameters.keys())
    assert "row" not in param_names
    assert "index" not in param_names


# ---------------------------------------------------------------------------
# _parse_points helper
# ---------------------------------------------------------------------------


def test_parse_points_from_int():
    assert _parse_points(35000) == 35000.0


def test_parse_points_from_float():
    assert _parse_points(35000.5) == 35000.5


def test_parse_points_from_string_with_commas():
    assert _parse_points("35,000") == 35000.0


def test_parse_points_from_string_with_unit():
    assert _parse_points("35000 miles") == 35000.0


def test_parse_points_from_invalid_returns_inf():
    assert _parse_points("N/A") == float("inf")


def test_parse_points_from_empty_string_returns_inf():
    assert _parse_points("") == float("inf")


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
# num_stops filter — cash flights (string stops)
# ---------------------------------------------------------------------------


def _make_cash_mixed_stops_state() -> dict:
    return {
        "last_cash_search": {
            "results": dict(CASH_FLIGHTS_MIXED_STOPS),
            "route": "SFO-NRT",
        }
    }


def test_cash_num_stops_nonstop():
    ctx = _make_tool_context(_make_cash_mixed_stops_state())
    result = get_flight_context(search_type="cash", num_stops=0, tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "UA837"


def test_cash_num_stops_one_stop():
    ctx = _make_tool_context(_make_cash_mixed_stops_state())
    result = get_flight_context(search_type="cash", num_stops=1, tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "DL200"


def test_cash_num_stops_two_stops():
    ctx = _make_tool_context(_make_cash_mixed_stops_state())
    result = get_flight_context(search_type="cash", num_stops=2, tool_context=ctx)
    assert len(result) == 1
    assert result[0]["flight_number"] == "AA300"


# ---------------------------------------------------------------------------
# CashFlightSummary schema
# ---------------------------------------------------------------------------


def test_cash_flight_summary_schema():
    """CashFlightSummary must have same lean shape as AwardFlightSummary."""
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
    from travel_concierge.sub_agents.planning.agent import cash_flight_search_agent
    from travel_concierge.tools.search import CashFlightsSelection, CashFlightSummary

    assert cash_flight_search_agent.output_schema is CashFlightSummary
    assert cash_flight_search_agent.output_schema is not CashFlightsSelection


# ---------------------------------------------------------------------------
# PLANNING_AGENT_INSTR covers cash format
# ---------------------------------------------------------------------------


def test_planning_prompt_cash_table_format():
    from travel_concierge.sub_agents.planning.prompt import PLANNING_AGENT_INSTR

    assert "cash" in PLANNING_AGENT_INSTR.lower()


def test_cash_flight_search_instr_has_summary_rule():
    from travel_concierge.sub_agents.planning.prompt import CASH_FLIGHT_SEARCH_INSTR

    assert "SUMMARY OUTPUT" in CASH_FLIGHT_SEARCH_INSTR
    assert "total_found" in CASH_FLIGHT_SEARCH_INSTR
    assert "search_params" in CASH_FLIGHT_SEARCH_INSTR


# ---------------------------------------------------------------------------
# search_type normalization
# ---------------------------------------------------------------------------


def test_search_type_case_insensitive_cash():
    """LLM may pass 'Cash' or 'CASH' — should load cash results."""
    ctx = _make_tool_context(_cash_state())
    for variant in ("Cash", "CASH", "cash "):
        result = get_flight_context(search_type=variant, tool_context=ctx)
        assert len(result) == 2, f"expected 2 cash flights for search_type={variant!r}"


def test_search_type_case_insensitive_award():
    """LLM may pass 'Award' or 'AWARD ' — should load award results."""
    ctx = _make_tool_context(_award_state())
    for variant in ("Award", "AWARD", " award"):
        result = get_flight_context(search_type=variant, tool_context=ctx)
        assert len(result) == 3, f"expected 3 award flights for search_type={variant!r}"


def test_search_type_unknown_returns_empty():
    """An unrecognised search_type should return [] instead of silently returning award."""
    ctx = _make_tool_context(_award_state())
    result = get_flight_context(search_type="points", tool_context=ctx)
    assert result == []
