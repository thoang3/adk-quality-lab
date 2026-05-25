"""Unit tests for travel_concierge.tools.flights._filter_flights.

Covers every filter parameter and their combinations.  Uses a small
self-contained fixture so tests are fully offline and deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make travel_concierge importable from the examples tree
sys.path.insert(0, str(Path(__file__).parents[1] / "examples" / "travel-concierge"))

from travel_concierge.tools.flights import (
    _count_stops,
    _departure_time,
    _filter_flights,
    _first_leg,
    _matches_airline,
    _parse_price,
    _parse_stops_string,
)


# ---------------------------------------------------------------------------
# Shared fixture data — minimal but covers all filter fields
# ---------------------------------------------------------------------------

def _make_itinerary(
    flight_number: str,
    airline: str,
    departure_time: str,   # "YYYY-MM-DD HH:MM" (SerpAPI nested format)
    price: int,
    total_duration: int,   # minutes
    num_stops: int = 0,
    travel_class: str = "Economy",
    airline_logo: str = "",
) -> dict:
    """Build a minimal SerpAPI itinerary dict."""
    legs = [
        {
            "departure_airport": {"name": "Origin Airport", "id": "ORG", "time": departure_time},
            "arrival_airport": {"name": "Dest Airport", "id": "DST", "time": "2026-07-01 22:00"},
            "flight_number": flight_number,
            "airline": airline,
            "airline_logo": airline_logo,
            "travel_class": travel_class,
            "duration": total_duration,
        }
    ]
    return {
        "flights": legs,
        "total_duration": total_duration,
        "price": price,
        "type": "One way",
        "airline_logo": airline_logo,
    }


# 8 itineraries covering a range of values
FLIGHTS: list[dict] = [
    _make_itinerary("JL 57",  "JAL",           "2026-07-01 07:30", price=650,  total_duration=750,  num_stops=0, travel_class="Economy"),
    _make_itinerary("JL 59",  "JAL",           "2026-07-01 22:00", price=620,  total_duration=760,  num_stops=0, travel_class="Economy"),
    _make_itinerary("NH 101", "ANA",           "2026-07-01 09:00", price=720,  total_duration=800,  num_stops=1, travel_class="Economy"),
    _make_itinerary("NH 201", "ANA",           "2026-07-01 14:00", price=490,  total_duration=950,  num_stops=1, travel_class="Business Class"),
    _make_itinerary("CX 840", "Cathay Pacific", "2026-07-01 11:30", price=580,  total_duration=870,  num_stops=1, travel_class="Economy"),
    _make_itinerary("CX 880", "Cathay Pacific", "2026-07-01 16:00", price=810,  total_duration=900,  num_stops=2, travel_class="Business Class"),
    _make_itinerary("UA 837", "United",         "2026-07-01 08:00", price=540,  total_duration=820,  num_stops=0, travel_class="Economy"),
    _make_itinerary("UA 839", "United",         "2026-07-01 23:30", price=1100, total_duration=780,  num_stops=0, travel_class="First"),
]


# ---------------------------------------------------------------------------
# _first_leg
# ---------------------------------------------------------------------------

class TestFirstLeg:
    def test_returns_first_leg_from_itinerary(self):
        leg = {"flight_number": "JL 57", "airline": "JAL"}
        itinerary = {"flights": [leg, {"flight_number": "JL 735"}], "price": 700}
        assert _first_leg(itinerary) is leg

    def test_falls_back_to_itinerary_when_no_flights_key(self):
        flat = {"flight_number": "JL 57", "airline": "JAL", "price": 700}
        assert _first_leg(flat) is flat

    def test_falls_back_when_flights_is_empty(self):
        d = {"flights": [], "price": 700}
        assert _first_leg(d) is d


# ---------------------------------------------------------------------------
# _parse_stops_string
# ---------------------------------------------------------------------------

class TestParseStopsString:
    def test_integer_passthrough(self):
        assert _parse_stops_string(0) == 0
        assert _parse_stops_string(2) == 2

    def test_nonstop_string(self):
        assert _parse_stops_string("Nonstop") == 0
        assert _parse_stops_string("nonstop") == 0

    def test_n_stops_string(self):
        assert _parse_stops_string("1 stop(s)") == 1
        assert _parse_stops_string("2 stop(s)") == 2
        assert _parse_stops_string("3 stop(s)") == 3

    def test_none_or_empty(self):
        assert _parse_stops_string(None) == -1
        assert _parse_stops_string("") == -1

    def test_unparseable(self):
        assert _parse_stops_string("many") == -1


# ---------------------------------------------------------------------------
# _departure_time
# ---------------------------------------------------------------------------

class TestDepartureTime:
    def test_serpapi_nested_format(self):
        f = {"flights": [{"departure_airport": {"time": "2026-07-01 09:45"}}]}
        assert _departure_time(f) == "09:45"

    def test_flat_departure_time_with_date(self):
        f = {"departure_time": "2026-07-01 13:55"}
        assert _departure_time(f) == "13:55"

    def test_flat_departure_time_hhmm_only(self):
        f = {"departure_time": "13:55"}
        assert _departure_time(f) == "13:55"

    def test_depart_time_field(self):
        f = {"depart_time": "06:30"}
        assert _departure_time(f) == "06:30"

    def test_sentinel_when_missing(self):
        assert _departure_time({}) == "99:99"

    def test_sentinel_excludes_from_before_filter(self):
        result = _filter_flights([{"price": 500, "total_duration": 600}], departure_before="23:59")
        assert result == []


# ---------------------------------------------------------------------------
# _matches_airline
# ---------------------------------------------------------------------------

class TestMatchesAirline:
    def test_iata_prefix_on_flight_number(self):
        f = _make_itinerary("JL 57", "JAL", "2026-07-01 07:00", 600, 700)
        assert _matches_airline(f, "JL")

    def test_full_name_fragment(self):
        f = _make_itinerary("CX 840", "Cathay Pacific", "2026-07-01 11:00", 580, 870)
        assert _matches_airline(f, "CATHAY")
        assert _matches_airline(f, "PACIFIC")

    def test_no_match(self):
        f = _make_itinerary("JL 57", "JAL", "2026-07-01 07:00", 600, 700)
        assert not _matches_airline(f, "CX")

    def test_multi_leg_matches_any_leg(self):
        # Two-leg itinerary: JL then NH — both codes should match
        f = {
            "flights": [
                {"flight_number": "JL 57", "airline": "JAL"},
                {"flight_number": "NH 101", "airline": "ANA"},
            ],
            "price": 700, "total_duration": 800,
        }
        assert _matches_airline(f, "JL")
        assert _matches_airline(f, "NH")
        assert not _matches_airline(f, "CX")


# ---------------------------------------------------------------------------
# _filter_flights — individual parameters
# ---------------------------------------------------------------------------

class TestFilterByFlightNumber:
    def test_exact_match(self):
        result = _filter_flights(FLIGHTS, flight_number="JL 57")
        assert len(result) == 1
        assert result[0]["flights"][0]["flight_number"] == "JL 57"

    def test_case_insensitive(self):
        result = _filter_flights(FLIGHTS, flight_number="jl 57")
        assert len(result) == 1

    def test_no_spaces(self):
        result = _filter_flights(FLIGHTS, flight_number="JL57")
        assert len(result) == 1

    def test_no_match(self):
        result = _filter_flights(FLIGHTS, flight_number="AA 999")
        assert result == []


class TestFilterByAirline:
    def test_iata_prefix(self):
        result = _filter_flights(FLIGHTS, airline="JL")
        assert len(result) == 2
        assert all(f["flights"][0]["airline"] == "JAL" for f in result)

    def test_name_fragment(self):
        result = _filter_flights(FLIGHTS, airline="CATHAY")
        assert len(result) == 2

    def test_ana_by_nh_prefix(self):
        result = _filter_flights(FLIGHTS, airline="NH")
        assert len(result) == 2
        assert all(f["flights"][0]["airline"] == "ANA" for f in result)

    def test_no_match(self):
        result = _filter_flights(FLIGHTS, airline="QR")
        assert result == []


class TestFilterByNumStops:
    def test_nonstop_via_layovers(self):
        f_nonstop = {**FLIGHTS[0]}                              # no layovers key → 0 stops
        f_onestop = {**FLIGHTS[2], "layovers": [{"duration": 90, "name": "NRT", "id": "NRT"}]}
        f_twostop = {**FLIGHTS[5], "layovers": [{"duration": 90, "name": "NRT", "id": "NRT"},
                                                 {"duration": 120, "name": "ICN", "id": "ICN"}]}
        pool = [f_nonstop, f_onestop, f_twostop]

        assert len(_filter_flights(pool, num_stops=0)) == 1
        assert len(_filter_flights(pool, num_stops=1)) == 1
        assert len(_filter_flights(pool, num_stops=2)) == 1
        assert len(_filter_flights(pool, num_stops=3)) == 0

    def test_empty_layovers_is_nonstop(self):
        f = {**FLIGHTS[0], "layovers": []}
        assert _count_stops(f) == 0

    def test_count_stops_legacy_flat_fields(self):
        # Fallback for non-SerpAPI flat dicts
        assert _count_stops({"stops": "Nonstop"}) == 0
        assert _count_stops({"num_stops": 2}) == 2


class TestFilterByCabinClass:
    def test_economy(self):
        result = _filter_flights(FLIGHTS, cabin_class="economy")
        assert all(f["flights"][0]["travel_class"].lower() == "economy" for f in result)
        assert len(result) == 5  # JL57, JL59, NH101, CX840, UA837

    def test_business(self):
        result = _filter_flights(FLIGHTS, cabin_class="business class")
        assert len(result) == 2  # NH201, CX880

    def test_first(self):
        result = _filter_flights(FLIGHTS, cabin_class="first")
        assert len(result) == 1
        assert result[0]["flights"][0]["flight_number"] == "UA 839"

    def test_case_insensitive(self):
        assert _filter_flights(FLIGHTS, cabin_class="ECONOMY") == \
               _filter_flights(FLIGHTS, cabin_class="economy")

    def test_no_match(self):
        assert _filter_flights(FLIGHTS, cabin_class="premium_economy") == []


class TestFilterByDepartureTime:
    def test_departure_before_morning(self):
        # Before 10:00: JL57 (07:30), NH101 (09:00), UA837 (08:00)
        result = _filter_flights(FLIGHTS, departure_before="10:00")
        times = [_departure_time(f) for f in result]
        assert all(t < "10:00" for t in times)
        assert len(result) == 3

    def test_departure_after_evening(self):
        # At or after 20:00: JL59 (22:00), UA839 (23:30)
        result = _filter_flights(FLIGHTS, departure_after="20:00")
        times = [_departure_time(f) for f in result]
        assert all(t >= "20:00" for t in times)
        assert len(result) == 2

    def test_afternoon_window(self):
        # 12:00 <= t < 18:00: CX840 (11:30 excluded), NH201 (14:00), CX880 (16:00)
        result = _filter_flights(FLIGHTS, departure_after="12:00", departure_before="18:00")
        times = [_departure_time(f) for f in result]
        assert all("12:00" <= t < "18:00" for t in times)
        assert len(result) == 2  # NH201, CX880

    def test_boundary_before_is_exclusive(self):
        # departure_before="09:00" should NOT include NH101 at exactly 09:00
        result = _filter_flights(FLIGHTS, departure_before="09:00")
        times = [_departure_time(f) for f in result]
        assert "09:00" not in times

    def test_boundary_after_is_inclusive(self):
        # departure_after="09:00" SHOULD include NH101 at exactly 09:00
        result = _filter_flights(FLIGHTS, departure_after="09:00")
        times = [_departure_time(f) for f in result]
        assert "09:00" in times


class TestFilterByMaxPrice:
    def test_all_pass(self):
        result = _filter_flights(FLIGHTS, max_price=2000)
        assert len(result) == len(FLIGHTS)

    def test_none_pass(self):
        result = _filter_flights(FLIGHTS, max_price=100)
        assert result == []

    def test_partial(self):
        # prices: 490, 540, 580, 620, 650, 720, 810, 1100
        result = _filter_flights(FLIGHTS, max_price=650)
        prices = [f["price"] for f in result]
        assert all(p <= 650 for p in prices)
        assert 490 in prices
        assert 1100 not in prices

    def test_exact_boundary(self):
        # max_price=620 should include the $620 flight
        result = _filter_flights(FLIGHTS, max_price=620)
        assert any(f["price"] == 620 for f in result)

    def test_missing_price_excluded(self):
        # Itinerary without a price field → _parse_price returns inf → excluded
        f_no_price = {k: v for k, v in FLIGHTS[0].items() if k != "price"}
        result = _filter_flights([f_no_price], max_price=9999)
        assert result == []

    def test_string_price_format(self):
        # Production FlightInfo.price is a string like "$732" — must still filter correctly
        f_str_price = {**FLIGHTS[0], "price": "$649"}
        assert len(_filter_flights([f_str_price], max_price=700)) == 1
        assert len(_filter_flights([f_str_price], max_price=600)) == 0

    def test_parse_price_helper(self):
        assert _parse_price(732) == 732.0
        assert _parse_price("$732") == 732.0
        assert _parse_price("1,234") == 1234.0
        assert _parse_price("$1,234.50") == 1234.50
        assert _parse_price(None) == float("inf")
        assert _parse_price("N/A") == float("inf")


class TestFilterByMaxDuration:
    def test_all_pass(self):
        result = _filter_flights(FLIGHTS, max_duration_minutes=9999)
        assert len(result) == len(FLIGHTS)

    def test_none_pass(self):
        result = _filter_flights(FLIGHTS, max_duration_minutes=100)
        assert result == []

    def test_partial(self):
        # durations: 750, 760, 780, 800, 820, 870, 900, 950
        result = _filter_flights(FLIGHTS, max_duration_minutes=800)
        durations = [f["total_duration"] for f in result]
        assert all(d <= 800 for d in durations)
        assert 750 in durations
        assert 950 not in durations

    def test_exact_boundary(self):
        result = _filter_flights(FLIGHTS, max_duration_minutes=750)
        assert any(f["total_duration"] == 750 for f in result)

    def test_missing_duration_excluded(self):
        f_no_dur = {k: v for k, v in FLIGHTS[0].items() if k != "total_duration"}
        result = _filter_flights([f_no_dur], max_duration_minutes=9999)
        assert result == []

    def test_duration_minutes_field_name(self):
        # Production FlightInfo uses duration_minutes instead of total_duration
        f_prod = {**{k: v for k, v in FLIGHTS[0].items() if k != "total_duration"},
                  "duration_minutes": 750}
        assert len(_filter_flights([f_prod], max_duration_minutes=800)) == 1
        assert len(_filter_flights([f_prod], max_duration_minutes=700)) == 0


# ---------------------------------------------------------------------------
# Combinations (AND logic)
# ---------------------------------------------------------------------------

class TestFilterCombinations:
    def test_airline_and_cabin(self):
        # ANA economy only → NH101
        result = _filter_flights(FLIGHTS, airline="NH", cabin_class="economy")
        assert len(result) == 1
        assert result[0]["flights"][0]["flight_number"] == "NH 101"

    def test_price_and_morning(self):
        # Under $700 AND before 10:00: JL57 (650, 07:30), UA837 (540, 08:00)
        result = _filter_flights(FLIGHTS, max_price=700, departure_before="10:00")
        assert len(result) == 2
        assert all(f["price"] <= 700 for f in result)
        assert all(_departure_time(f) < "10:00" for f in result)

    def test_duration_and_price(self):
        # Under 800 min AND under $700: JL57 (750min, $650), JL59 (760min, $620), UA839 (780min, $1100 excluded)
        result = _filter_flights(FLIGHTS, max_duration_minutes=800, max_price=700)
        assert all(f["total_duration"] <= 800 for f in result)
        assert all(f["price"] <= 700 for f in result)

    def test_all_filters_produce_single_result(self):
        # Narrow down to exactly JL 57: JAL, economy, before 10:00, price<=700, duration<=800
        result = _filter_flights(
            FLIGHTS,
            airline="JL",
            cabin_class="economy",
            departure_before="10:00",
            max_price=700,
            max_duration_minutes=800,
        )
        assert len(result) == 1
        assert result[0]["flights"][0]["flight_number"] == "JL 57"

    def test_contradictory_filters_return_empty(self):
        result = _filter_flights(FLIGHTS, departure_before="06:00", departure_after="20:00")
        assert result == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_input(self):
        assert _filter_flights([], airline="JL") == []
        assert _filter_flights([], max_price=999) == []

    def test_no_filters_returns_all(self):
        assert _filter_flights(FLIGHTS) == FLIGHTS

    def test_none_filters_ignored(self):
        # Passing None explicitly for each param → same as no filter
        result = _filter_flights(
            FLIGHTS,
            flight_number=None,
            airline=None,
            num_stops=None,
            cabin_class=None,
            departure_before=None,
            departure_after=None,
            max_price=None,
            max_duration_minutes=None,
        )
        assert result == FLIGHTS
