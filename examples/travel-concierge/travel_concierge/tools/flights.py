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

"""Flight context tool — lazy-loads flight results from session state on demand.

Architecture note (eval harness):
    The pure filter logic lives in ``_filter_flights()``, which takes a plain
    ``list[dict]`` and returns a filtered subset.  ``get_flight_context()`` is
    the thin ADK agent tool that loads from session state and then delegates
    to ``_filter_flights()``.

    The eval rater (``adk_quality_lab/raters/deterministic.py``) imports
    ``_filter_flights`` directly and applies it to fixture data to derive the
    expected ground-truth subset for each turn in a multi-turn eval case:

        from travel_concierge.tools.flights import _filter_flights
        expected = _filter_flights(fixture_flights, **scenario["turn_params"][turn_idx])

    This ensures the rater and the agent use *identical* filter logic — no
    separate ``FixtureFilter`` class, no logic drift.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _parse_stops_string(stops_value: object) -> int:
    """Convert a cash-flight stops string to an integer stop count.

    Cash ``FlightInfo.stops`` is a human-readable string such as "Nonstop",
    "1 stop(s)", or "2 stop(s)".

    Returns:
        Integer stop count, or -1 if the value cannot be parsed.
    """
    if isinstance(stops_value, int):
        return stops_value
    if not stops_value:
        return -1
    s = str(stops_value).strip().lower()
    if s == "nonstop":
        return 0
    # "1 stop(s)", "2 stop(s)", "3 stop(s)", etc. — extracts the leading digit as the count
    try:
        return int(s.split()[0])
    except (ValueError, IndexError):
        return -1


def _filter_flights(
    flights: list[dict],
    flight_number: str | None = None,
    airline: str | None = None,
    num_stops: int | None = None,
    cabin_class: str | None = None,
    departure_before: str | None = None,
    departure_after: str | None = None,
    max_price: int | None = None,
    max_duration_minutes: int | None = None,
) -> list[dict]:
    """Pure filter over a list of flight dicts — no session state, no ADK dependency.

    Used by the eval rater (``adk_quality_lab/raters/deterministic.py``) to
    derive Turn N ground truth from fixture data.  All filter parameters
    combine with AND logic.

    Args:
        flights: Flat list of flight dicts (SerpAPI cash format).
        flight_number: Match a specific flight (e.g. "QR701"). Case-insensitive.
        airline: Filter by IATA code or name fragment (e.g. "NH", "ANA").
        num_stops: Exact stop count (0 = nonstop).
        cabin_class: Cabin class string (e.g. "business"). Case-insensitive.
        departure_before: Keep flights departing before HH:MM (e.g. "10:00").
        departure_after: Keep flights departing at or after HH:MM (e.g. "18:00").
        max_price: Keep itineraries with ``price`` ≤ this value (USD integer).
        max_duration_minutes: Keep itineraries with ``total_duration`` ≤ this
            value (minutes, e.g. 900 for "under 15 hours").

    Returns:
        Filtered list of flight dicts.
    """
    result = flights

    if flight_number:
        fn = flight_number.upper().replace(" ", "")
        result = [
            f for f in result
            if _first_leg(f).get("flight_number", "").upper().replace(" ", "") == fn
        ]
        logger.debug(f"_filter_flights: after flight_number ({fn}): {len(result)}")

    if airline:
        code = airline.upper().strip()
        result = [f for f in result if _matches_airline(f, code)]
        logger.debug(f"_filter_flights: after airline ({code}): {len(result)}")

    if num_stops is not None:
        result = [
            f for f in result
            if _count_stops(f) == num_stops
        ]
        logger.debug(f"_filter_flights: after num_stops ({num_stops}): {len(result)}")

    if cabin_class:
        cc = cabin_class.lower().strip()
        result = [
            f for f in result
            if _first_leg(f).get("travel_class", f.get("cabin_class", "")).lower() == cc
        ]
        logger.debug(f"_filter_flights: after cabin_class ({cc}): {len(result)}")

    if departure_before:
        result = [
            f for f in result
            if _departure_time(f) < departure_before
        ]
        logger.debug(f"_filter_flights: after departure_before ({departure_before}): {len(result)}")

    if departure_after:
        result = [
            f for f in result
            if _departure_time(f) >= departure_after
        ]
        logger.debug(f"_filter_flights: after departure_after ({departure_after}): {len(result)}")

    if max_price is not None:
        result = [
            f for f in result
            if _parse_price(f.get("price")) <= max_price
        ]
        logger.debug(f"_filter_flights: after max_price ({max_price}): {len(result)}")

    if max_duration_minutes is not None:
        result = [
            f for f in result
            if isinstance(f.get("total_duration", f.get("duration_minutes")), (int, float))
            and f.get("total_duration", f.get("duration_minutes")) <= max_duration_minutes
        ]
        logger.debug(f"_filter_flights: after max_duration_minutes ({max_duration_minutes}): {len(result)}")

    logger.info(f"_filter_flights: returning {len(result)} flights")
    return result


def _parse_price(value: object) -> float:
    """Parse a price value to float. Handles int/float (SerpAPI raw) and
    string format (``FlightInfo.price`` e.g. ``"$732"`` or ``"732"``).
    Returns ``inf`` if unparseable so the itinerary is excluded by max_price."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("$", "").replace(",", "").strip())
        except ValueError:
            pass
    return float("inf")


def _first_leg(itinerary: dict) -> dict:
    """Return the first leg dict from a SerpAPI itinerary, or the itinerary itself
    if it is already a flat flight dict (fallback for non-SerpAPI formats)."""
    legs = itinerary.get("flights")
    if isinstance(legs, list) and legs:
        return legs[0]
    return itinerary


def _count_stops(itinerary: dict) -> int:
    """Return the number of stops for a SerpAPI itinerary.

    SerpAPI represents stops via the ``layovers`` list (one entry per
    connection).  A nonstop flight has no ``layovers`` key (or an empty list).
    If the itinerary has a ``flights`` key (SerpAPI format), missing ``layovers``
    means 0 stops.  Falls back to legacy ``stops`` / ``num_stops`` flat fields.
    """
    # SerpAPI format: presence of "flights" key is the discriminator
    if "flights" in itinerary:
        return len(itinerary.get("layovers") or [])
    # Legacy flat fields
    return _parse_stops_string(itinerary.get("stops", itinerary.get("num_stops", -1)))


def _departure_time(itinerary: dict) -> str:
    """Extract a comparable HH:MM departure time string from a flight dict.

    Checks the SerpAPI nested structure ``flights[0].departure_airport.time``
    (e.g. "2026-07-01 09:45") first, then falls back to flat fields
    ``depart_time`` / ``departure_time`` for non-SerpAPI formats.
    Returns "99:99" as a sentinel if no time can be extracted — excluded by any
    ``departure_before`` filter rather than silently included.
    """
    # SerpAPI: departure time is on the first leg
    leg = _first_leg(itinerary)
    dep = leg.get("departure_airport", {})
    if isinstance(dep, dict):
        t = dep.get("time", "")
        if t and len(t) >= 5:
            return t[-5:] if " " in t else t[:5]
    # Flat departure_time field
    t = leg.get("departure_time", "")
    if t and len(t) >= 5:
        return t[-5:] if " " in t else t[:5]
    # Legacy depart_time field ("HH:MM" only)
    t = leg.get("depart_time", "")
    if t and len(t) >= 5 and t[2] == ":":
        return t[:5]
    return "99:99"  # sentinel — excluded by any departure_before filter


def _matches_airline(itinerary: dict, code: str) -> bool:
    """Check if any leg of an itinerary matches an airline code or name fragment."""
    legs = itinerary.get("flights") or [itinerary]
    for leg in legs:
        # SerpAPI: "airline" is a display name string on each leg
        airline_str = leg.get("airline", "")
        if isinstance(airline_str, str) and code in airline_str.upper():
            return True
        # Also check flight_number prefix (e.g. "JL" matches "JL 57")
        flight_num = leg.get("flight_number", "")
        if isinstance(flight_num, str) and flight_num.upper().replace(" ", "").startswith(code):
            return True
    return False


def get_flight_context(
    tool_context: object,
    flight_number: str | None = None,
    airline: str | None = None,
    num_stops: int | None = None,
    max_price: int | None = None,
    departure_before: str | None = None,
    departure_after: str | None = None,
    max_duration_minutes: int | None = None,
) -> dict:
    """Lazy-load flight details from session state with optional filtering.

    Reads the ``search_results_cash`` key populated by the eval harness
    (``_fixture_to_session_state``) or by ``search_cash_flights_with_count``.
    All filter parameters combine with AND logic.

    Args:
        tool_context: ADK ToolContext injected by the framework.
        flight_number: Exact flight number match (e.g. "UA869").
        airline: IATA code or name fragment (e.g. "UA", "United").
        num_stops: Exact stop count (0 = nonstop).
        max_price: Maximum price in USD.
        departure_before: HH:MM upper bound for departure time.
        departure_after: HH:MM lower bound for departure time.
        max_duration_minutes: Maximum total flight duration in minutes.

    Returns:
        Dict with 'total_stored', 'total_returned', and 'flights' list.
    """
    flights: list[dict] = getattr(tool_context, "state", {}).get("search_results_cash", [])
    if not isinstance(flights, list):
        flights = []

    filtered = _filter_flights(
        flights,
        flight_number=flight_number,
        airline=airline,
        num_stops=num_stops,
        max_price=max_price,
        departure_before=departure_before,
        departure_after=departure_after,
        max_duration_minutes=max_duration_minutes,
    )
    return {
        "total_stored": len(flights),
        "total_returned": len(filtered),
        "flights": filtered,
    }
