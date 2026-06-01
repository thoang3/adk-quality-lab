#!/usr/bin/env python3
"""Shared helpers for playground minimal cash-flight variants."""

from datetime import date, datetime, timedelta
from typing import Optional

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from pydantic import BaseModel

from travel_concierge.prompt import ROOT_AGENT_INSTR
from travel_concierge.shared_libraries.model import MODEL
from travel_concierge.tools.profile import get_current_profile
from travel_concierge.tools.search import (
    search_cash_flights,
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
    """A list of minimal cash-flight records for format-aligned experiments."""

    flights: list[MinimalCashFlightInfo]


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


async def search_cash_flights_full_selection(
    flight_request: FlightRequest,
    tool_context=None,
) -> dict:
    """Return flattened cash flights for MinimalCashFlightsSelection schema."""
    result = await search_cash_flights(flight_request, tool_context)

    if isinstance(result, dict) and tuple(result) == ("error",):
        return {"flights": []}

    flights = []
    if isinstance(result, dict):
        for cabin_flights in result.values():
            if isinstance(cabin_flights, list):
                for flight in cabin_flights:
                    if hasattr(flight, "model_dump"):
                        flight_data = flight.model_dump()
                    elif isinstance(flight, dict):
                        flight_data = flight
                    else:
                        continue

                    flights.append(
                        {
                            "date": flight_data.get("date", ""),
                            "airline": flight_data.get("airline", ""),
                            "flight_number": flight_data.get("flight_number", ""),
                            "depart_time": flight_data.get("depart_time", ""),
                            "arrive_time": flight_data.get("arrive_time", ""),
                            "duration_minutes": flight_data.get("duration_minutes", 0),
                            "stops": flight_data.get("stops", ""),
                            "travel_class": flight_data.get("travel_class", ""),
                            "price": flight_data.get("price", ""),
                        }
                    )

    return {"flights": flights}


async def search_cash_flights_date_range_selection(
    flight_request: FlightDateRangeRequest,
    tool_context=None,
) -> dict:
    """Return flattened minimal cash flights across a date range.

    Reuses `search_cash_flights_full_selection` for each date in the inclusive
    range `[start_date, end_date]` and aggregates the results into one payload.
    """

    start = datetime.strptime(flight_request.start_date, "%Y-%m-%d").date()
    end = datetime.strptime(flight_request.end_date, "%Y-%m-%d").date()

    if end < start:
        return {"flights": []}

    all_flights: list[dict] = []
    current_date: date = start

    while current_date <= end:
        daily_request = FlightRequest(
            origin=flight_request.origin,
            destination=flight_request.destination,
            outbound_date=current_date.isoformat(),
            cabin_class=flight_request.cabin_class,
            is_direct=flight_request.is_direct,
            max_stops=flight_request.max_stops,
            preferred_airlines=flight_request.preferred_airlines,
            max_price=flight_request.max_price,
        )

        daily_result = await search_cash_flights_full_selection(daily_request, tool_context)
        flights = daily_result.get("flights", []) if isinstance(daily_result, dict) else []
        if isinstance(flights, list):
            all_flights.extend(flights)

        current_date += timedelta(days=1)

    def _price_to_int(value: object) -> int:
        try:
            return int(str(value).replace(",", "").strip())
        except Exception:
            return 10**9

    all_flights.sort(
        key=lambda flight: (
            flight.get("date", ""),
            _price_to_int(flight.get("price")),
            int(flight.get("duration_minutes", 0) or 0),
        )
    )

    return {"flights": all_flights}


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