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

"""Wrapper to Google Search Grounding with custom prompt."""

import asyncio
import logging
import os
import re
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.google_search_tool import google_search
from pydantic import BaseModel, field_validator
from serpapi.google_search import GoogleSearch

from travel_concierge.shared_libraries.model import MODEL

# Initialize Logger (inherits from main app configuration)
logger = logging.getLogger(__name__)

DEBUG_LOGGING_ENABLED = (
    os.getenv("DEBUG_LOGGING_ENABLED", "false").lower() == "true"
)  # Control verbose debug logs


_search_agent = Agent(
    model=MODEL,
    name="google_search_grounding",
    description="An agent providing Google-search grounding capability",
    instruction="""
    Answer the user's question directly using google_search grounding tool; Provide a brief but concise response.
    Rather than a detail response, provide the immediate actionable item for a tourist or traveler, in a single sentence.
    Do not ask the user to check or look up information for themselves, that's your role; do your best to be informative.
    """,
    tools=[google_search],
)

google_search_grounding = AgentTool(agent=_search_agent)


class SearchFilters(BaseModel):
    """Filters extracted from user query for pre-search filtering."""

    cabin_class: str = ""  # Economy, Premium Economy, Business, First
    preferred_airlines: list[str] = []  # List of airline codes or names
    max_points: int = 0  # Maximum points threshold (0 = no limit)
    max_price: int = 0  # Maximum cash price threshold (0 = no limit)
    direct_only: bool = False  # Only show direct flights


class FlightRequest(BaseModel):
    origin: str
    destination: str
    outbound_date: str
    cabin_class: str = ""
    is_direct: bool = False  # Deprecated: use max_stops instead
    max_stops: Optional[int] = None  # noqa: UP045 — ADK function calling requires Optional[X] over X|None
    # New filter fields
    preferred_airlines: list[str] = []
    max_points: int = 0
    max_price: int = 0


class FlightDateRangeRequest(BaseModel):
    origin: str
    destination: str
    start_date: str
    end_date: str
    # New filter fields
    cabin_class: str = ""
    is_direct: bool = False  # Deprecated: use max_stops instead
    max_stops: Optional[int] = None  # noqa: UP045 — ADK function calling requires Optional[X] over X|None
    preferred_airlines: list[str] = []
    max_points: int = 0


# ==============================================
# 🎛️ UI Filter Defaults Helper
# ==============================================
def apply_ui_filter_defaults(
    flight_request: FlightRequest | FlightDateRangeRequest,
    tool_context: ToolContext = None,
) -> None:
    """Apply UI filter defaults from session state to flight request.

    UI filters are sent by the frontend and stored in session state. They serve as
    defaults when the LLM doesn't extract specific values from the user's query.

    Precedence: User's explicit query > LLM-extracted params > UI filter defaults

    Args:
        flight_request: The flight request to modify in place
        tool_context: ADK tool context with access to session state
    """
    if not tool_context or not tool_context.state:
        return

    ui_filters = tool_context.state.get("ui_filters", {})
    if not ui_filters:
        return

    logger.info(f"Applying UI filter defaults: {ui_filters}")

    # Only apply UI filter if the request field is empty/default
    # This ensures LLM-extracted values have precedence

    # cabin_class: only apply if empty
    if not flight_request.cabin_class and ui_filters.get("cabin_class"):
        flight_request.cabin_class = ui_filters["cabin_class"]
        logger.info(
            f"Applied UI filter default: cabin_class={flight_request.cabin_class}"
        )

    # max_stops: apply if not explicitly set by LLM
    if (
        hasattr(flight_request, "max_stops")
        and flight_request.max_stops is None
        and ui_filters.get("max_stops") is not None
    ):
        flight_request.max_stops = ui_filters["max_stops"]
        # Sync is_direct for backwards compatibility
        if ui_filters["max_stops"] == 0:
            flight_request.is_direct = True
        logger.info(f"Applied UI filter default: max_stops={flight_request.max_stops}")

    # is_direct: only apply if False (default) and max_stops not set
    if (
        hasattr(flight_request, "is_direct")
        and not flight_request.is_direct
        and flight_request.max_stops is None
        and ui_filters.get("is_direct")
    ):
        flight_request.is_direct = True
        logger.info("Applied UI filter default: is_direct=True")

    # preferred_airlines: only apply if empty
    if not flight_request.preferred_airlines and ui_filters.get("preferred_airlines"):
        flight_request.preferred_airlines = ui_filters["preferred_airlines"]
        logger.info(
            f"Applied UI filter default: preferred_airlines={flight_request.preferred_airlines}"
        )

    # max_points: only apply if 0 (no limit)
    if flight_request.max_points == 0 and ui_filters.get("max_points"):
        flight_request.max_points = ui_filters["max_points"]
        logger.info(
            f"Applied UI filter default: max_points={flight_request.max_points}"
        )

    # max_price: only apply if 0 (no limit) and field exists
    if (
        hasattr(flight_request, "max_price")
        and flight_request.max_price == 0
        and ui_filters.get("max_price")
    ):
        flight_request.max_price = ui_filters["max_price"]
        logger.info(f"Applied UI filter default: max_price={flight_request.max_price}")


class FlightInfo(BaseModel):
    """Cash flight information from SerpAPI with normalized fields.

    Field Classification:
    - **Legacy display fields**: airline, price, duration, stops, departure, arrival, travel_class, airline_logo
      (kept for backwards compatibility with UI)

    - **Matching-critical fields** (REQUIRED): flight_number, origin, destination, date
      These are enforced by Pydantic (no defaults) and guaranteed by SerpAPI response parsing.
      SerpAPI provides 100% coverage via departure_airport.id, arrival_airport.id, and flight_number fields.

    - **Display metadata** (REQUIRED): depart_time, arrive_time, duration_minutes
      Used for UI display. SerpAPI provides these via departure_airport.time and arrival_airport.time fields.
      Made required to ensure consistent data population and UI rendering.

    - **Booking link**: booking_url - Direct link to book this flight (Google Flights URL with route/date/cabin)
    """

    airline: str
    price: str
    duration: str
    stops: str
    departure: str  # Full departure string (for backwards compatibility)
    arrival: str  # Full arrival string (for backwards compatibility)
    travel_class: str
    airline_logo: str
    flight_number: str  # Required for flight matching

    # Normalized fields for matching algorithm (required for matching)
    origin: str  # Airport code (e.g., "JFK") - required for route matching
    destination: str  # Airport code (e.g., "CDG") - required for route matching
    date: str  # Flight date (YYYY-MM-DD) - required for date matching

    # Display fields (required for UI rendering)
    depart_time: str  # Time string (e.g., "20:25")
    arrive_time: str  # Time string (e.g., "12:00")
    duration_minutes: int  # Duration in minutes
    type: str = "cash"
    booking_url: str = ""  # Google Flights booking URL (empty if generation fails)

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate that date is in YYYY-MM-DD format."""
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date must be in YYYY-MM-DD format, got: {v}")
        return v


class CashFlightsSelection(BaseModel):
    """A list of cash flights from the search."""

    flights: list[FlightInfo]


# ==============================================
# 🛫 IATA Code → Display Name Lookup (canonical source of truth)
# ==============================================
# This is the single authoritative mapping of IATA codes to display names.
# Backend resolves all airline fields to display names before sending to frontend.
# Frontend must NOT perform its own name resolution — it just renders what it receives.
IATA_TO_AIRLINE_NAME: dict[str, str] = {
    "AA": "American Airlines",
    "AC": "Air Canada",
    "AF": "Air France",
    "AI": "Air India",
    "AM": "Aeromexico",
    "AR": "Aerolineas Argentinas",
    "AS": "Alaska Airlines",
    "A3": "Aegean Airlines",
    "AV": "Avianca",
    "AY": "Finnair",
    "AZ": "ITA Airways",
    "B6": "JetBlue",
    "BA": "British Airways",
    "BR": "EVA Air",
    "CA": "Air China",
    "CI": "China Airlines",
    "CM": "Copa Airlines",
    "CX": "Cathay Pacific",
    "CZ": "China Southern",
    "DL": "Delta Air Lines",
    "EK": "Emirates",
    "ET": "Ethiopian Airlines",
    "EY": "Etihad Airways",
    "FI": "Icelandair",
    "F9": "Frontier Airlines",
    "FJ": "Fiji Airways",
    "G4": "Allegiant Air",
    "GA": "Garuda Indonesia",
    "HA": "Hawaiian Airlines",
    "HU": "Hainan Airlines",
    "IB": "Iberia",
    "JL": "Japan Airlines",
    "JQ": "Jetstar",
    "JU": "Air Serbia",
    "KE": "Korean Air",
    "KL": "KLM",
    "LA": "LATAM Airlines",
    "LH": "Lufthansa",
    "LO": "LOT Polish Airlines",
    "LX": "Swiss International Air Lines",
    "MH": "Malaysia Airlines",
    "MS": "EgyptAir",
    "MU": "China Eastern",
    "NH": "All Nippon Airways",
    "NK": "Spirit Airlines",
    "NZ": "Air New Zealand",
    "OS": "Austrian Airlines",
    "OZ": "Asiana Airlines",
    "PR": "Philippine Airlines",
    "QF": "Qantas",
    "QR": "Qatar Airways",
    "RJ": "Royal Jordanian",
    "SA": "South African Airways",
    "SK": "SAS",
    "SN": "Brussels Airlines",
    "SQ": "Singapore Airlines",
    "SU": "Aeroflot",
    "SV": "Saudia",
    "TG": "Thai Airways",
    "TK": "Turkish Airlines",
    "TP": "TAP Air Portugal",
    "UA": "United Airlines",
    "UX": "Air Europa",
    "VA": "Virgin Australia",
    "VN": "Vietnam Airlines",
    "VS": "Virgin Atlantic",
    "WN": "Southwest Airlines",
    "WS": "WestJet",
}


def iata_to_display_name(iata_code: str) -> str:
    """Resolve an IATA 2-letter airline code to a human-readable display name.

    Args:
        iata_code: IATA 2-letter code (e.g. 'AA', 'DL', 'NH').

    Returns:
        Display name (e.g. 'American Airlines') or the original code if unknown.
    """
    return IATA_TO_AIRLINE_NAME.get(iata_code.upper().strip(), iata_code)


def iata_from_logo_url(logo_url: str) -> str:
    """Extract IATA airline code from a SerpAPI/Google Flights logo URL.

    SerpAPI always returns airline_logo URLs of the form:
        https://www.gstatic.com/flights/airline_logos/70px/AA.png

    Args:
        logo_url: The airline_logo URL returned by SerpAPI.

    Returns:
        Uppercase IATA code (e.g. 'AA'), or '' if the URL is empty/malformed.
    """
    if not logo_url:
        return ""
    filename = logo_url.split("/")[-1]  # 'AA.png'
    code = filename.replace(".png", "").upper()  # 'AA'
    return code if code.isalnum() and 2 <= len(code) <= 3 else ""


# ==============================================
# 🛫 Airline Name Normalization Helper (used for matching/filtering only)
# ==============================================
def normalize_airline_name(airline: str) -> str:
    """Normalize airline names for matching.

    Args:
        airline: Airline name or code

    Returns:
        Normalized airline name
    """
    # Common airline name variations
    normalization_map = {
        "all nippon airways": "ANA",
        "ana": "ANA",
        "japan airlines": "JAL",
        "jal": "JAL",
        "united airlines": "United",
        "united": "United",
        "american airlines": "American",
        "american": "American",
        "delta air lines": "Delta",
        "delta": "Delta",
        "air canada": "Air Canada",
        "virgin atlantic": "Virgin Atlantic",
        "british airways": "British Airways",
        "lufthansa": "Lufthansa",
        "singapore airlines": "Singapore Airlines",
        "cathay pacific": "Cathay Pacific",
        "emirates": "Emirates",
        "qatar airways": "Qatar Airways",
        "etihad": "Etihad",
        "turkish airlines": "Turkish Airlines",
        "air france": "Air France",
        "klm": "KLM",
        "iberia": "Iberia",
        "swiss": "Swiss",
        "austrian": "Austrian",
        "qantas": "Qantas",
        "eva air": "EVA Air",
        "asiana": "Asiana",
        "korean air": "Korean Air",
    }

    airline_lower = airline.lower().strip()
    return normalization_map.get(airline_lower, airline)


# ==============================================
# 🛫 Cabin Name Normalization Helper
# ==============================================
def normalize_cabin_name(cabin: str) -> str:
    """Normalize cabin class names for consistent matching.

    Args:
        cabin: Cabin name from API or user input

    Returns:
        Normalized cabin name in lowercase without spaces
    """
    # Map various cabin name formats to standardized lowercase no-space format
    normalization_map = {
        "economy": "economy",
        "premium economy": "premiumeconomy",
        "premium": "premiumeconomy",  # API often returns "premium" for "Premium Economy"
        "business": "business",
        "first": "first",
        "first class": "first",
    }

    cabin_lower = cabin.lower().strip()
    return normalization_map.get(cabin_lower, cabin_lower.replace(" ", ""))


# ==============================================
# 🔍 Client-Side Filter Application Helper
# ==============================================
def apply_client_side_filters(
    flights: list[FlightInfo],
    flight_request: FlightRequest | FlightDateRangeRequest,
    context: str = "cache",
) -> list[FlightInfo]:
    """Apply client-side filters to flights after cache retrieval.

    Filters are applied AFTER cache lookup to enable SUPERSET caching strategy.
    Cache stores broader results (all stops, all prices, all airlines) and this
    function narrows to user's specific request.

    This eliminates code duplication across 4 cache hit paths and ensures
    consistent filter behavior throughout the application.

    Args:
        flights: List of flights to filter
        flight_request: User's search parameters with filter values
        context: Description for logging (e.g., "cache", "API", "all-cabins extraction")

    Returns:
        Filtered list of flights matching user's criteria

    Filters Applied:
        1. max_stops: Remove flights exceeding user's stop count preference
        2. max_price: Remove flights exceeding user's price budget
        3. preferred_airlines: Keep only flights from user's preferred airlines
    """
    original_count = len(flights)
    filtered_flights = flights

    # Filter by max_stops
    if hasattr(flight_request, "max_stops") and flight_request.max_stops is not None:
        filtered_by_stops = []
        for flight in filtered_flights:
            # Treat "Nonstop" as always acceptable
            if getattr(flight, "stops", None) == "Nonstop":
                filtered_by_stops.append(flight)
                continue
            try:
                stops_value = getattr(flight, "stops", None)
                stops_count = int(str(stops_value).split()[0])
                if stops_count <= flight_request.max_stops:
                    filtered_by_stops.append(flight)
            except (ValueError, IndexError, AttributeError):
                # Skip flights with malformed stops data
                logger.warning(f"Malformed stops data in {context}: {stops_value}")
                continue
        filtered_flights = filtered_by_stops

    # Filter by max_price
    if hasattr(flight_request, "max_price") and flight_request.max_price > 0:
        filtered_flights = [
            flight
            for flight in filtered_flights
            if int(flight.price) <= flight_request.max_price
        ]

    # Filter by preferred_airlines
    if flight_request.preferred_airlines and len(flight_request.preferred_airlines) > 0:
        preferred_normalized = [
            normalize_airline_name(a) for a in flight_request.preferred_airlines
        ]
        filtered_flights = [
            flight
            for flight in filtered_flights
            if normalize_airline_name(flight.airline) in preferred_normalized
        ]

    if original_count != len(filtered_flights):
        logger.info(
            f"🔍 Applied client-side filters ({context}): {original_count} -> {len(filtered_flights)} flights"
        )

    return filtered_flights


# ==============================================
# 🔢 Safe Numeric Coercion Helper
# ==============================================
def safe_int_coerce(value, default=0):
    """Safely coerce a value to integer with proper financial rounding (ROUND_HALF_UP).

    Uses Python's Decimal with ROUND_HALF_UP to ensure consistent half-up rounding
    (0.5 always rounds up) for financial values like taxes. This avoids Python's
    default banker's rounding which can cause 1-cent discrepancies.

    Args:
        value: Value to convert (can be int, float, str, or None)
        default: Default value to return if conversion fails (default: 0)

    Returns:
        Integer value with half-up rounding, or default if conversion fails

    Examples:
        safe_int_coerce(120) -> 120
        safe_int_coerce(120.7) -> 121 (rounds up)
        safe_int_coerce("120") -> 120
        safe_int_coerce("120.50") -> 121 (rounds up: 0.5 -> 1)
        safe_int_coerce("120.49") -> 120 (rounds down)
        safe_int_coerce(121.5) -> 122 (rounds up: 0.5 -> 1)
        safe_int_coerce("invalid") -> 0 (default)
        safe_int_coerce(None) -> 0 (default)
    """
    try:
        # Handle None or empty string
        if value is None or value == "":
            return default
        # Convert to Decimal for precise financial arithmetic
        # Use ROUND_HALF_UP to ensure 0.5 always rounds up (financial convention)
        decimal_value = Decimal(str(value))
        return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError, ArithmeticError):
        return default


# ==============================================
# 🔗 Booking URL Generation Functions
# ==============================================
def generate_booking_url(flight_data: dict) -> str:
    """Generate booking URL for cash flights using Google Flights.

    Args:
        flight_data: Dict with keys: departure_airport (dict with 'id'),
                     arrival_airport (dict with 'id'), date (str), travel_class (str)

    Returns:
        Google Flights URL with route/date/cabin pre-filled

    Note: Premium economy is NOT supported in Google Flights natural language queries.
    For premium economy, we generate a generic search URL without cabin class.
    """
    # Extract airport codes from nested dicts
    origin = flight_data.get("departure_airport", {}).get("id", "")
    destination = flight_data.get("arrival_airport", {}).get("id", "")
    date = flight_data.get("date", "")
    cabin_class = flight_data.get("travel_class", "").lower()

    # Map cabin class terms to Google Flights compatible terms
    # Premium economy excluded - not supported in natural language queries
    cabin_mapping = {
        "economy": "economy",
        "business": "business",
        "first": "first class",
        "first class": "first class",
    }

    # Get mapped cabin (None for premium economy or unsupported)
    mapped_cabin = cabin_mapping.get(cabin_class, None)

    # Explicitly exclude premium economy variants
    if cabin_class in ["premium", "premium economy"]:
        mapped_cabin = None

    if origin and destination and date:
        query = f"Flights from {origin} to {destination} on {date}"
        if mapped_cabin:
            query += f" {mapped_cabin}"
        query += " one way"
        encoded_query = urllib.parse.quote(query)
        return f"https://www.google.com/travel/flights?q={encoded_query}"
    else:
        return "https://www.google.com/travel/flights"


# ==============================================
# 🛫 Fetch Data from SerpAPI
# ==============================================
async def run_search(params):
    """Generic function to run SerpAPI searches asynchronously."""
    try:
        return await asyncio.to_thread(lambda: GoogleSearch(params).get_dict())
    except Exception as e:
        logger.exception(f"SerpAPI search error: {e!s}")
        # raise HTTPException(status_code=500, detail=f"Search API error: {str(e)}")


async def search_cash_flights(
    flight_request: FlightRequest, tool_context: ToolContext | None = None
):
    """Fetch real-time cash flight details from Google Flights using SerpAPI."""
    logger.info(
        f"Searching flights via API: {flight_request.origin} to {flight_request.destination}"
    )

    # Cabin class codes: 1=Economy, 2=Premium Economy, 3=Business, 4=First
    cabin_classes = {1: "Economy", 2: "Premium Economy", 3: "Business", 4: "First"}
    all_results = {}

    # Prefer environment-configured key; fall back to embedded key if present
    SERP_API_KEY = os.environ.get("SERP_API_KEY")

    for cabin_code, cabin_name in cabin_classes.items():
        # Filter by cabin class if specified
        if (
            flight_request.cabin_class
            and cabin_name.lower() != flight_request.cabin_class.lower()
        ):
            continue

        logger.info(f"Searching {cabin_name} cabin class...")

        params = {
            "api_key": SERP_API_KEY,
            "engine": "google_flights",
            "type": 2,
            "hl": "en",
            "gl": "us",
            "departure_id": flight_request.origin.strip().upper(),
            "arrival_id": flight_request.destination.strip().upper(),
            "outbound_date": flight_request.outbound_date,
            "travel_class": cabin_code,
            "currency": "USD",
        }

        # SerpAPI stops parameter mapping:
        # 0 = any number of stops (default), 1 = nonstop only, 2 = 1 stop or fewer, 3 = 2 stops or fewer
        # Our max_stops: 0=nonstop, 1=up to 1 stop, 2=up to 2 stops, None=any
        if (
            hasattr(flight_request, "max_stops")
            and flight_request.max_stops is not None
        ):
            if flight_request.max_stops == 0:
                params["stops"] = 1  # Nonstop only
            else:
                params["stops"] = 3  # Up to 2 stops; client-side filter trims further
        elif flight_request.is_direct:
            params["stops"] = 1
        else:
            params["stops"] = 3  # Up to 2 stops

        logger.info(f"params:\n {params}")
        search_results = await run_search(params)
        if "error" in search_results:
            logger.error(
                f"Flight search error for {cabin_name}: {search_results['error']}"
            )
            # Continue to next cabin instead of failing immediately
            continue

        if search_results and "other_flights" in search_results:
            if DEBUG_LOGGING_ENABLED:
                logger.debug(
                    f"Found {len(search_results.get('other_flights', []))} other flights, {len(search_results.get('best_flights', []))} best flights"
                )
        best_flights = search_results.get("best_flights", [])
        best_flights.extend(search_results.get("other_flights", []))

        formatted_flights = []
        for flight in best_flights:
            if not flight.get("flights") or len(flight["flights"]) == 0:
                continue

            first_leg = flight["flights"][0]
            last_leg = flight["flights"][-1]  # Get the last leg for final arrival


            # Extract ALL flight numbers from all legs
            flight_numbers = []
            for leg in flight["flights"]:
                leg_flight_number = leg.get("flight_number", "")
                if leg_flight_number:
                    # Normalize: remove spaces for consistent matching (e.g., "AF 7" -> "AF7")
                    leg_flight_number = leg_flight_number.replace(" ", "")
                    flight_numbers.append(leg_flight_number)

            flight_number = ", ".join(flight_numbers) if flight_numbers else ""

            # Log raw flight data for debugging
            logger.info(
                f"🔍 Raw SerpAPI flight legs: airline={first_leg.get('airline')}, flight_numbers={flight_number}, departure_time={first_leg.get('departure_airport', {}).get('time')}"
            )
            if not flight_number:
                logger.warning(
                    f"⚠️ No flight_numbers found in any leg. Keys available in first_leg: {list(first_leg.keys())}"
                )

            # Format duration as "Xh Ym" instead of "N min"
            total_mins = flight.get("total_duration", 0)
            if total_mins and isinstance(total_mins, (int, float)) and total_mins > 0:
                hours = int(total_mins) // 60
                mins = int(total_mins) % 60
                duration_str = f"{hours}h {mins}m"
            else:
                duration_str = "N/A"

            # Extract normalized airport codes and times
            departure_airport = first_leg.get("departure_airport", {})
            arrival_airport = last_leg.get("arrival_airport", {})

            origin_code = departure_airport.get("id", "")
            destination_code = arrival_airport.get("id", "")

            # SerpAPI returns full datetime like "2026-03-09 20:25", extract time portion
            depart_datetime = departure_airport.get("time", "")
            arrive_datetime = arrival_airport.get("time", "")
            depart_time = (
                depart_datetime.split()[-1] if depart_datetime else ""
            )  # "2026-03-09 20:25" -> "20:25"
            arrive_time = (
                arrive_datetime.split()[-1] if arrive_datetime else ""
            )  # "2026-03-10 12:00" -> "12:00"

            # Build full departure/arrival strings (for backwards compatibility)
            departure_full = f"{departure_airport.get('name', 'Unknown')} ({origin_code}) at {depart_datetime}"
            arrival_full = f"{arrival_airport.get('name', 'Unknown')} ({destination_code}) at {arrive_datetime}"

            # Generate booking URL
            booking_url = generate_booking_url(
                {
                    "departure_airport": departure_airport,
                    "arrival_airport": arrival_airport,
                    "date": flight_request.outbound_date,
                    "travel_class": cabin_name,
                }
            )

            # Resolve airline display name from the logo URL's embedded IATA code.
            # SerpAPI's airline_logo is always ".../70px/AA.png" — the IATA code is
            # the filename stem.  This is more reliable than the airline string field
            # which mirrors Google Flights UI names (inconsistent: "American" vs "British Airways").
            _logo_url = first_leg.get("airline_logo", "")
            _iata = iata_from_logo_url(_logo_url)
            _airline_display = (
                iata_to_display_name(_iata)
                if _iata
                else first_leg.get("airline", "Unknown Airline")
            )

            formatted_flights.append(
                FlightInfo(
                    airline=_airline_display,
                    price=str(flight.get("price", "N/A")),
                    duration=duration_str,
                    stops="Nonstop"
                    if len(flight["flights"]) == 1
                    else f"{len(flight['flights']) - 1} stop(s)",
                    departure=departure_full,
                    arrival=arrival_full,
                    travel_class=cabin_name,  # Use cabin name (Business, Economy, etc.) not numeric code
                    airline_logo=_logo_url,
                    flight_number=flight_number,  # ✅ FIXED: Now captures flight number!
                    # Normalized fields
                    origin=origin_code,
                    destination=destination_code,
                    depart_time=depart_time,
                    arrive_time=arrive_time,
                    duration_minutes=int(total_mins) if total_mins else 0,
                    date=flight_request.outbound_date,
                    type="cash",
                    booking_url=booking_url,
                )
            )

        logger.info(f"Found {len(formatted_flights)} flights")
        all_results[cabin_name] = formatted_flights

    # Check if we got any results at all
    if not all_results:
        return {"error": "No flight results found for any cabin class"}

    # Apply client-side filters (max_stops, max_price, preferred_airlines)
    for cabin_name, flights in all_results.items():
        if isinstance(flights, list):
            all_results[cabin_name] = apply_client_side_filters(
                flights, flight_request, f"API {cabin_name}"
            )

    return all_results


async def search_cash_flights_with_count(
    flight_request: FlightRequest, tool_context: ToolContext | None = None
) -> dict:
    """Wrapper around search_cash_flights that returns compact summary metadata.

    Returning the full cash flight results in the tool response makes the
    payload unnecessarily large for the sub-agent LLM (typically 10–15 k tokens
    for 80 flights). This wrapper therefore returns only the total count the LLM
    needs to write a short intro.

    Args:
        flight_request: Flight search parameters
        tool_context: ADK tool context for session state

    Returns:
        Dict with a single 'total_count' key on success (full results are in
        session state), or ``{"error": "<message>"}`` if every cabin-class
        search failed — preserving the underlying error so the sub-agent can
        surface a useful message instead of silently reporting zero flights.
    """
    result = await search_cash_flights(flight_request, tool_context)
    # search_cash_flights returns {"error": "..."} (sole key) when the SerpAPI
    # call fails for every cabin class.  Pass the error through so the sub-agent
    # can surface a useful message instead of silently reporting total_count=0.
    if tuple(result) == ("error",):
        return result
    total = sum(
        len(flights) for flights in result.values() if isinstance(flights, list)
    )
    return {"total_count": total}

