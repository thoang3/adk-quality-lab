#!/usr/bin/env python3
"""Shared helpers for playground minimal cash-flight variants."""

from typing import Optional

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel

from travel_concierge.prompt import ROOT_AGENT_INSTR
from travel_concierge import MODEL
from adk_quality_lab_wiring.tools.profile import get_current_profile
from adk_quality_lab_wiring.tools.fixture_flight_search import (
    search_flights,
    search_flights_range,
)


class FlightRequest(BaseModel):
    """Playground-local cash flight request schema (single-date)."""

    origin: str
    destination: str
    outbound_date: str
    cabin_class: str = ""
    is_direct: bool = False
    max_stops: Optional[int] = None
    preferred_airlines: list[str] = []
    max_price: int = 0


class FlightDateRangeRequest(BaseModel):
    """Playground-local cash flight request schema (date-range)."""

    origin: str
    destination: str
    start_date: str
    end_date: str
    cabin_class: str = ""
    is_direct: bool = False
    max_stops: Optional[int] = None
    preferred_airlines: list[str] = []
    max_price: int = 0


class MinimalCashFlightInfo(BaseModel):
    """Minimal cash-flight fields aligned with markdown-table presentation."""

    date: str
    airline: str
    flight_number: str
    depart_time: str
    arrive_time: str
    duration_minutes: int
    stops: str
    travel_class: str
    price: str


class MinimalCashFlightsSelection(BaseModel):
    """Structured cash-flight response with an NL message channel.

    `message` carries all natural-language communication with the user
    (clarifying questions, summaries, follow-up answers, error notices).
    `flights` carries the structured flight data (empty list when no search
    has been performed yet or when answering a non-search follow-up).
    """

    message: str = ""  # NL channel: clarifications, summaries, follow-up answers
    flights: list[MinimalCashFlightInfo] = []


FULL_CASH_FLIGHT_SEARCH_INSTR = """Generate full cash flight search results.
- Support two request types:
    1) Single-date: requires origin, destination, outbound_date.
    2) Date-range: requires origin, destination, start_date, end_date.
- Ask for any missing required fields before calling a search tool.
- When all required fields are present, call the appropriate search tool.
- Return a non-empty JSON object with this exact shape:
  {"flights": [ ... ]}
- Include each flight with only these fields:
    date, airline, flight_number, depart_time, arrive_time, duration_minutes, stops, travel_class, price
- Do NOT return summary-only output.
"""


def _parse_serpapi_flights(
    raw_flights: list[dict],
    outbound_date: str,
    cabin_class: str,
) -> list[dict]:
    """Parse raw SerpAPI flight dicts into MinimalCashFlightInfo-compatible dicts."""
    result = []
    for flight in raw_flights:
        legs = flight.get("flights", [])
        if not legs:
            continue
        first_leg = legs[0]
        last_leg = legs[-1]

        flight_numbers = [
            leg.get("flight_number", "").replace(" ", "")
            for leg in legs
            if leg.get("flight_number")
        ]
        flight_number = ", ".join(flight_numbers)

        depart_dt = first_leg.get("departure_airport", {}).get("time", "")
        arrive_dt = last_leg.get("arrival_airport", {}).get("time", "")
        depart_time = depart_dt.split()[-1] if depart_dt else ""
        arrive_time = arrive_dt.split()[-1] if arrive_dt else ""

        total_mins = flight.get("total_duration", 0)
        stops = "Nonstop" if len(legs) == 1 else f"{len(legs) - 1} stop(s)"

        # Use the date embedded by search_flights_range (outbound_date field)
        # or fall back to the passed-in outbound_date for single-date calls.
        flight_date = flight.get("outbound_date", outbound_date)

        result.append({
            "date": flight_date,
            "airline": first_leg.get("airline", "Unknown"),
            "flight_number": flight_number,
            "depart_time": depart_time,
            "arrive_time": arrive_time,
            "duration_minutes": int(total_mins) if total_mins else 0,
            "stops": stops,
            "travel_class": cabin_class or "economy",
            "price": str(flight.get("price", "N/A")),
        })
    return result


async def search_cash_flights_full_selection(
    flight_request: FlightRequest,
    tool_context=None,
) -> dict:
    """Return flattened cash flights for MinimalCashFlightsSelection schema."""
    import json as _json
    raw = await search_flights(
        origin=flight_request.origin,
        destination=flight_request.destination,
        outbound_date=flight_request.outbound_date,
        cabin_class=flight_request.cabin_class or "economy",
        adults=1,
        tool_context=tool_context,
    )
    data = _json.loads(raw)
    if "error" in data and not data.get("best_flights") and not data.get("other_flights"):
        return {"flights": []}
    all_raw = data.get("best_flights", []) + data.get("other_flights", [])
    return {"flights": _parse_serpapi_flights(
        all_raw, flight_request.outbound_date, flight_request.cabin_class
    )}


async def search_cash_flights_date_range_selection(
    flight_request: FlightDateRangeRequest,
    tool_context=None,
) -> dict:
    """Return flattened minimal cash flights across a date range."""
    import json as _json
    raw = await search_flights_range(
        origin=flight_request.origin,
        destination=flight_request.destination,
        start_date=flight_request.start_date,
        end_date=flight_request.end_date,
        cabin_class=flight_request.cabin_class or "economy",
        adults=1,
        tool_context=tool_context,
    )
    data = _json.loads(raw)
    all_raw = data.get("best_flights", []) + data.get("other_flights", [])
    flights = _parse_serpapi_flights(all_raw, "", flight_request.cabin_class)

    def _price_to_int(value: object) -> int:
        try:
            return int(str(value).replace(",", "").strip())
        except Exception:
            return 10**9

    flights.sort(key=lambda f: (
        f.get("date", ""),
        _price_to_int(f.get("price")),
        int(f.get("duration_minutes", 0) or 0),
    ))
    return {"flights": flights}


def _log_agent_context(callback_context) -> None:
    """Minimal before_agent_callback that logs the active agent name."""
    import logging
    logger = logging.getLogger(__name__)
    agent_name = getattr(callback_context, "agent_name", "unknown")
    logger.debug("agent_callback: %s", agent_name)


def build_cash_flight_search_agent_full_details() -> Agent:
    """Create the shared cash search sub-agent for playground variants."""
    return Agent(
        model=MODEL,
        name="cash_flight_search_agent_full_details",
        description="Playground variant: return cash flight records in minimal aligned schema.",
        instruction=FULL_CASH_FLIGHT_SEARCH_INSTR,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_schema=MinimalCashFlightsSelection,
        tools=[
            FunctionTool(func=search_cash_flights_full_selection),
            FunctionTool(func=search_cash_flights_date_range_selection),
        ],
    )


def build_planning_tools(cash_flight_search_agent: Agent) -> list:
    """Build standard tool list used by minimal cash planning variants."""
    return [
        FunctionTool(get_current_profile),
        AgentTool(agent=cash_flight_search_agent),
    ]


def build_root_agent_minimal_cash(
    planning_agent: Agent,
    *,
    name: str,
    description: str,
) -> Agent:
    """Build root agent wrapper for a minimal cash planning variant."""
    return Agent(
        model=MODEL,
        name=name,
        description=description,
        instruction=ROOT_AGENT_INSTR,
        tools=[FunctionTool(get_current_profile)],
        sub_agents=[planning_agent],
        before_agent_callback=_log_agent_context,
    )