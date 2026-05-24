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

"""Flight context tool — lazy-loads flight results from session state on demand."""

from __future__ import annotations

import logging

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


def _parse_stops_string(stops_value: object) -> int:
    """Convert a cash-flight stops string to an integer stop count.

    Cash ``FlightInfo.stops`` is a human-readable string such as "Nonstop",
    "1 stop(s)", or "2 stop(s)".  Award flights store ``num_stops`` directly
    as an integer, so no conversion is needed for those.

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


def get_flight_context(
    search_type: str = "award",
    flight_number: str | None = None,
    airline: str | None = None,
    num_stops: int | None = None,
    max_points: int | None = None,
    cabin_class: str | None = None,
    tool_context: ToolContext | None = None,
) -> list[dict]:
    """Retrieve flight search results from session state, with optional filters.

    Call this when the user asks a question about flights from the current
    search results (e.g. "tell me about QR701", "which are nonstop?",
    "any Air France options?"). Use filter parameters to load only the
    relevant subset and keep token cost proportional to the question.

    Do NOT call this on the initial search response — use the total_found
    and search_params from the search agent's summary instead.

    Flights are identified by attribute (flight_number, airline, etc.) —
    never by row position, since the frontend table is sortable and row
    positions are unstable. If the user references a row number, ask them
    to clarify by flight number or airline instead.

    Args:
        search_type: Which search results to load — "award" (default) or "cash".
            Always pass the type matching the most recent search you delegated.
            No fallback between types: if "award" has no results, returns [],
            not cash flights (avoids silently returning the wrong data when
            both keys are populated after a compare_award_vs_cash call).
        flight_number: Match a specific flight (e.g. "QR701"). Case-insensitive.
        airline: Filter by IATA airline code or name (e.g. "AF", "Air France").
            Matches against the airlines list for award flights or the airline
            field for cash flights. Case-insensitive.
        num_stops: Filter by exact stop count (0 = nonstop, 1 = one-stop, etc.).
        max_points: Filter to flights costing ≤ this many points/miles.
            Only meaningful for award flights.
        cabin_class: Filter by cabin class (e.g. "business", "economy").
            Case-insensitive.
        tool_context: ADK tool context for session state access.

    Returns:
        Matching flight dicts from the specified search type,
        or an empty list if no search has been performed yet.
    """
    if not tool_context or not tool_context.state:
        logger.warning("get_flight_context: no tool_context or state available")
        return []

    # Normalize search_type so LLM variations ("Cash", "CASH", "award ") all work.
    normalized_type = search_type.strip().lower() if search_type else ""
    if normalized_type not in ("cash", "award"):
        logger.warning(
            f"get_flight_context: unknown search_type {search_type!r}, expected 'award' or 'cash'; returning []"
        )
        return []

    if normalized_type == "cash":
        search_data = tool_context.state.get("last_cash_search", {})
        # Cash results are keyed by cabin class: {"Business": [...], "Economy": [...]}
        raw_results = (
            search_data.get("results", {}) if isinstance(search_data, dict) else {}
        )
        flights: list[dict] = []
        if isinstance(raw_results, dict):
            for cabin_flights in raw_results.values():
                if isinstance(cabin_flights, list):
                    flights.extend(cabin_flights)
        logger.info(
            f"get_flight_context: loaded {len(flights)} cash flights from session state"
        )
    else:
        search_data = tool_context.state.get("last_award_search", {})
        flights = (
            search_data.get("results", []) if isinstance(search_data, dict) else []
        )
        logger.info(
            f"get_flight_context: loaded {len(flights)} award flights from session state"
        )

    # Apply filters — each is optional, all combine with AND logic
    if flight_number:
        fn = flight_number.upper().replace(" ", "")
        flights = [
            f
            for f in flights
            if f.get("flight_number", "").upper().replace(" ", "") == fn
        ]
        logger.debug(
            f"get_flight_context: after flight_number filter ({fn}): {len(flights)} flights"
        )

    if airline:
        code = airline.upper().strip()
        flights = [f for f in flights if _matches_airline(f, code)]
        logger.debug(
            f"get_flight_context: after airline filter ({code}): {len(flights)} flights"
        )

    if num_stops is not None:
        flights = [
            f
            for f in flights
            if _parse_stops_string(f.get("stops", f.get("num_stops", -1))) == num_stops
        ]
        logger.debug(
            f"get_flight_context: after num_stops filter ({num_stops}): {len(flights)} flights"
        )

    if max_points is not None:
        flights = [
            f
            for f in flights
            if _parse_points(f.get("points", f.get("mileage_cost", ""))) <= max_points
        ]
        logger.debug(
            f"get_flight_context: after max_points filter ({max_points}): {len(flights)} flights"
        )

    if cabin_class:
        cc = cabin_class.lower().strip()
        flights = [
            f
            for f in flights
            if f.get("travel_class", f.get("cabin_class", "")).lower() == cc
        ]
        logger.debug(
            f"get_flight_context: after cabin_class filter ({cc}): {len(flights)} flights"
        )

    logger.info(f"get_flight_context: returning {len(flights)} flights")
    return flights


def _matches_airline(flight: dict, code: str) -> bool:
    """Check if a flight matches an airline code or name fragment."""
    # Award flights: "airline" is a list of IATA codes or names
    airlines_list = flight.get("airline", [])
    if isinstance(airlines_list, list):
        for a in airlines_list:
            if code in a.upper():
                return True
    elif isinstance(airlines_list, str) and code in airlines_list.upper():
        return True

    # Cash flights: "airline" is a display name string
    airline_str = flight.get("airline_name", flight.get("airline", ""))
    if isinstance(airline_str, str) and code in airline_str.upper():
        return True

    # Also check flight_number prefix (e.g. "AF" matches "AF276")
    flight_num = flight.get("flight_number", "")
    if isinstance(flight_num, str) and flight_num.upper().startswith(code):
        return True

    return False


def _parse_points(value: str | int | float) -> float:
    """Parse a points/miles value to a float for comparison."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").split()[0])
    except (ValueError, IndexError):
        return float("inf")
