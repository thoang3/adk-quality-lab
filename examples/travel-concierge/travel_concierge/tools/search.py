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
import copy
import json
import logging
import os
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import requests
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.google_search_tool import google_search
from pydantic import BaseModel, field_validator
from serpapi.google_search import GoogleSearch

from travel_concierge.shared_libraries.firebase import (
    get_user_api_key,
    get_user_api_key_status,
    update_user_api_key_last_used,
)
from travel_concierge.shared_libraries.model import MODEL
from travel_concierge.tools.cache import (
    Cache,
    canonicalize_search_params,
    compute_cache_key,
)
from travel_concierge.tools.mappings import PROGRAM_DISPLAY_NAMES, PROGRAM_NAME_MAPPING

# Initialize Logger (inherits from main app configuration)
logger = logging.getLogger(__name__)

# Configuration constants for award search behavior
MAX_TRIP_DETAIL_FETCHES = int(
    os.getenv("MAX_TRIP_DETAIL_FETCHES", "10")
)  # Limit trip detail API calls per search
MAX_API_RETRIES = int(
    os.getenv("MAX_API_RETRIES", "1")
)  # Number of retry attempts for failed API calls
DEBUG_LOGGING_ENABLED = (
    os.getenv("DEBUG_LOGGING_ENABLED", "false").lower() == "true"
)  # Control verbose debug logs


def get_program_display_name(source: str) -> str:
    """Convert raw API source to user-friendly program display name.

    Args:
        source: Raw API source (e.g., 'velocity', 'emirates', 'qatar')

    Returns:
        Friendly display name (e.g., 'Velocity Miles', 'Emirates Skywards', 'Qatar Avios')
    """
    if not source:
        return "Unknown Program"
    return PROGRAM_DISPLAY_NAMES.get(source.lower(), f"{source.title()} Miles")


def retry_api_call(func, *args, max_retries=MAX_API_RETRIES, delay_seconds=1, **kwargs):
    """Retry an API call with exponential backoff.

    Args:
        func: The function to call
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts
        delay_seconds: Initial delay between retries (increases with each retry)
        **kwargs: Keyword arguments for func

    Returns:
        The result from func, or None if all retries failed
    """
    import time

    retry_count = 0

    while retry_count <= max_retries:
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            retry_count += 1
            if retry_count <= max_retries:
                logger.warning(
                    f"⚠️ API call failed, retrying ({retry_count}/{max_retries}): {e}"
                )
                time.sleep(delay_seconds * retry_count)  # Exponential backoff
            else:
                logger.error(f"❌ API call failed after {max_retries} retries: {e}")
                return None


def check_award_search_readiness(tool_context: ToolContext = None) -> str:
    """Check if the user is ready for award searches (subscription tier + API key).

    This function validates both prerequisites for award flight searches:
    1. User has Premium, Pro, or Enterprise subscription (not free tier)
    2. User has a valid Seats.aero API key configured

    This consolidated check prevents the agent from attempting searches when either
    prerequisite is missing, providing clear, actionable error messages.

    Args:
        tool_context: ADK tool context containing session state with user_id and subscription

    Returns:
        A user-friendly message about readiness status:
        - Success: "✅ Ready for award searches."
        - Missing context: "Unable to check readiness - no session context available."
        - Not authenticated: "Please sign in to use award flight searches."
        - No subscription: "🔒 Award flight search requires a Premium or Pro subscription..."
        - No API key: "⚠️ Please add your Seats.aero API key in Edit Wallet..."
        - Invalid key: "⚠️ Your Seats.aero API key is invalid..."
    """
    # 1. Check session context first (infrastructure layer)
    if not tool_context or not tool_context.state:
        return "Unable to check readiness - no session context available."

    # 2. Check authentication (identity layer)
    user_id = tool_context.state.get("user_id")
    if not user_id:
        return "Please sign in to use award flight searches."

    # 3. Check subscription access (authorization layer)
    if not check_feature_access("award_search", tool_context):
        return "🔒 Award flight search requires a Premium or Pro subscription. Please upgrade to unlock award flight searches and find the best deals using your points and miles."

    # 3. Check API key status (only if subscription is valid)
    status = get_user_api_key_status(user_id, "seats_aero")

    if not status.get("has_key", False):
        # Check environment variable fallback (matches search_award_flights behavior)
        env_key = os.getenv("SEATS_AERO_API_KEY")
        if env_key:
            return "✅ Ready for award searches."
        return "⚠️ Please add your Seats.aero API key in Edit Wallet to search for award flights."

    if status.get("status") == "invalid":
        return "⚠️ Your Seats.aero API key is invalid. Please update it in Edit Wallet."

    return "✅ Ready for award searches."


def check_feature_access(feature_name: str, tool_context: ToolContext = None) -> bool:
    """Check if user has access to a premium feature.

    This function implements the BYPASS_SUBSCRIPTION feature for testing.
    It checks:
    1. BYPASS_SUBSCRIPTION environment variable (for testing)
    2. User subscription tier (for production)

    Args:
        feature_name: Name of the feature to check (e.g., 'award_search')
        tool_context: ADK tool context containing session state with user_id

    Returns:
        True if user has access, False otherwise
    """
    logger.info(f"🔐 Checking feature access for '{feature_name}'")

    # Check for BYPASS_SUBSCRIPTION environment variable (testing mode)
    bypass_value = os.getenv("BYPASS_SUBSCRIPTION", "")
    bypass_subscription = (bypass_value or "").lower() in ("true", "1", "yes")
    logger.info(
        f"🔐 BYPASS_SUBSCRIPTION env var: '{bypass_value}' -> bypass={bypass_subscription}"
    )

    if bypass_subscription:
        logger.info("🔐 ✅ Access granted via BYPASS_SUBSCRIPTION")
        return True

    # In production, check user subscription tier
    if not tool_context or not tool_context.state:
        logger.info("🔐 ❌ No tool_context or state - access denied")
        return False

    user_id = tool_context.state.get("user_id")
    logger.info(f"🔐 User ID: {user_id}")

    if not user_id:
        logger.info("🔐 ❌ No user_id - access denied")
        return False

    # Get subscription data from tool_context first (session state), fallback to Firebase
    try:
        subscription_tier = "free"  # Default

        # Try to get from session state first (faster, more reliable)
        if tool_context and tool_context.state:
            user_subscription = tool_context.state.get("user_subscription", {})
            subscription_tier = user_subscription.get("tier", "free")
            logger.info(
                f"🔐 Subscription from session state: tier='{subscription_tier}'"
            )

            # SMART FALLBACK: If session says free, verify with Firebase to catch post-upgrade race condition
            # This adds ~50-200ms latency only for free-tier checks (99% of paid users skip this)
            if subscription_tier == "free":
                from travel_concierge.shared_libraries.firebase import (
                    load_user_subscription,
                )

                user_subscription_firebase = load_user_subscription(user_id)

                if (
                    user_subscription_firebase
                    and user_subscription_firebase.get("tier") != "free"
                ):
                    # User upgraded! Session state is stale, update it
                    subscription_tier = user_subscription_firebase["tier"]
                    tool_context.state["user_subscription"] = user_subscription_firebase
                    logger.info(
                        f"🔐 ⚡ Race condition detected! Updated session state: tier='{subscription_tier}' (was stale)"
                    )
                else:
                    logger.info(
                        "🔐 Verified free tier with Firebase (no race condition)"
                    )
        else:
            # Fallback: load from Firebase (no session state available)
            from travel_concierge.shared_libraries.firebase import (
                load_user_subscription,
            )

            user_subscription = load_user_subscription(user_id)
            subscription_tier = (
                user_subscription.get("tier", "free") if user_subscription else "free"
            )
            logger.info(f"🔐 Subscription from Firebase: tier='{subscription_tier}'")

        # Define feature access by subscription tier
        feature_access = {
            "award_search": [
                "premium",
                "pro",
                "enterprise",
            ],  # Award search requires premium+
        }

        allowed_tiers = feature_access.get(feature_name, [])
        has_access = subscription_tier in allowed_tiers
        logger.info(
            f"🔐 Feature '{feature_name}' allowed tiers: {allowed_tiers}, user tier: '{subscription_tier}' -> access={has_access}"
        )

        return has_access

    except Exception as e:
        # Log error but default to no access for security
        logger.error(f"🔐 ❌ Error checking feature access for user {user_id}: {e}")
        return False


# Cache configuration
SEARCH_CACHE_ENABLED = os.getenv("SEARCH_CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL_MINUTES = int(os.getenv("CACHE_TTL_MINUTES", "15"))
_global_cache = (
    Cache(ttl_seconds=CACHE_TTL_MINUTES * 60) if SEARCH_CACHE_ENABLED else None
)

# from google.cloud import secretmanager


def _normalize_session_program_key(key: str) -> str:
    """Normalize program key from session state format to internal format.

    Session state uses keys like 'american_airlines', 'united_mileageplus'
    but our internal system uses 'aa_miles', 'united_miles', etc.

    This function maps between the two naming conventions.

    Args:
        key: Program key from session state (e.g., 'american_airlines')

    Returns:
        Normalized key for internal use (e.g., 'aa_miles')
    """
    key_lower = key.lower().strip()

    # Map session state keys to internal program names
    session_to_internal = {
        # Airline direct programs
        "american_airlines": "aa_miles",
        "american": "aa_miles",
        "aa": "aa_miles",
        "united_mileageplus": "united_miles",
        "united": "united_miles",
        "delta_skymiles": "delta_skymiles",
        "delta": "delta_skymiles",
        "alaska": "alaska_miles",
        "alaska_mileageplan": "alaska_miles",
        "ana_mileage_club": "ana_miles",
        "ana": "ana_miles",
        "jal_mileage_bank": "jal_miles",
        "jal": "jal_miles",
        "british_airways": "british_airways",
        "virgin_atlantic": "virgin_atlantic",
        "flying_blue": "flying_blue",
        "aeroplan": "aeroplan",
        "singapore_krisflyer": "singapore_krisflyer",
        "singapore": "singapore_krisflyer",
        "cathay_asia_miles": "cathay_asia_miles",
        "cathay": "cathay_asia_miles",
        "emirates_skywards": "emirates_skywards",
        "emirates": "emirates_skywards",
        "qantas_frequent_flyer": "qantas_points",
        "qantas": "qantas_points",
        "qatar_airways": "qatar_avios",
        "qatar": "qatar_avios",
        "etihad_guest": "etihad_guest",
        "etihad": "etihad_guest",
        # Bank transfer programs (keep as-is since they transfer to airline programs)
        "chase": "chase_ur",
        "chase_ur": "chase_ur",
        "amex": "amex_mr",
        "amex_mr": "amex_mr",
        "american_express": "amex_mr",
        "capital_one": "capital_one",
        "citi": "citi_thankyou",
        "citi_thankyou": "citi_thankyou",
    }

    # Look up in mapping
    if key_lower in session_to_internal:
        return session_to_internal[key_lower]

    # If not found, return lowercase version
    return key_lower


# def get_serpapi_key():
#     client = secretmanager.SecretManagerServiceClient()
#     name = "projects/potent-symbol-267207/secrets/serpapi-key/versions/latest"
#     response = client.access_secret_version(request={"name": name})
#     return response.payload.data.decode("UTF-8")

# SERP_API_KEY = get_serpapi_key()

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
    type: str = "cash"  # "cash" or "award"
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
# ✈️ Flight Number Normalization Helper
# ==============================================
def normalize_flight_numbers(flight_numbers):
    """Normalize flight numbers from Seats.aero API to comma-separated string.

    The Seats.aero /trips/{id} API can return FlightNumbers as either:
    - String: "QR714" or "QR714, QR810" (already comma-separated)
    - List: ["QR714"] or ["QR714", "QR810"]

    This function normalizes both formats to a consistent comma-separated string
    for downstream matching against cash flight numbers.

    Args:
        flight_numbers: Flight number(s) from API (str, list, or None)

    Returns:
        Normalized string like "QR714, QR810" or "N/A" if empty/invalid

    Examples:
        normalize_flight_numbers("QR714") -> "QR714"
        normalize_flight_numbers(["QR714"]) -> "QR714"
        normalize_flight_numbers(["QR714", "QR810"]) -> "QR714, QR810"
        normalize_flight_numbers("QR714, QR810") -> "QR714, QR810"
        normalize_flight_numbers(None) -> "N/A"
        normalize_flight_numbers([]) -> "N/A"
    """
    if not flight_numbers:
        return "N/A"

    # If already a string, return as-is
    if isinstance(flight_numbers, str):
        return flight_numbers.strip() or "N/A"

    # If list, join with comma-space
    if isinstance(flight_numbers, list):
        # Filter out empty strings and join
        nums = [str(num).strip() for num in flight_numbers if num]
        return ", ".join(nums) if nums else "N/A"

    # Fallback for unexpected types
    return str(flight_numbers).strip() or "N/A"


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


def generate_award_booking_url(flight_data: dict) -> str:
    """Generate booking URL for award flights using airline websites.

    Args:
        flight_data: Dict with keys: source (str), origin (str), destination (str),
                     date (str), cabin (str)

    Returns:
        Airline booking URL (parameterized for Alaska/Qantas, generic for others)

    For airlines that support URL parameters (Alaska, Qantas), generate
    parameterized URLs with route/date pre-filled. For others, use generic
    booking page URLs since Seats.aero Partner API doesn't provide direct
    booking links.
    """
    source = flight_data.get("source", "").lower()
    origin = flight_data.get("origin", "")
    destination = flight_data.get("destination", "")
    date = flight_data.get("date", "")
    cabin = flight_data.get("cabin", "economy").lower()

    # Map cabin classes to airline-specific codes
    cabin_mapping = {
        "economy": "ECO",
        "premium economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
        "first class": "FIRST",
    }

    # Airlines with parameterized URL support
    if source == "alaska" and origin and destination and date:
        # Alaska Airlines: Full parameter support with passenger count
        # A=1 (1 adult passenger) is required to avoid "must book at least 1 passenger" error
        encoded_origin = urllib.parse.quote(origin, safe="")
        encoded_destination = urllib.parse.quote(destination, safe="")
        encoded_date = urllib.parse.quote(date, safe="")
        return (
            "https://www.alaskaair.com/search/results"
            f"?O={encoded_origin}&D={encoded_destination}&OD={encoded_date}"
            "&A=1&RT=false&ShoppingMethod=onlineaward"
        )

    elif source == "qantas" and origin and destination and date:
        # Qantas: Full parameter support with cabin class
        cabin_code = cabin_mapping.get(cabin, "ECO")
        encoded_origin = urllib.parse.quote(origin, safe="")
        encoded_destination = urllib.parse.quote(destination, safe="")
        encoded_cabin_code = urllib.parse.quote(cabin_code, safe="")
        encoded_date = urllib.parse.quote(date, safe="")
        return (
            "https://www.qantas.com/us/en"
            f"?departureAirportCode={encoded_origin}"
            f"&arrivalAirportCode={encoded_destination}"
            f"&travelClass={encoded_cabin_code}"
            "&usePoints=true&tripType=O"
            f"&departureDate={encoded_date}"
        )

    # Generic booking page URLs for top 14 programs
    program_urls = {
        "united": "https://www.united.com/en/us",
        "american": "https://www.aa.com/booking",
        "delta": "https://www.delta.com/booking",
        "aeroplan": "https://www.aircanada.com/home/us/en/aco/flights",
        "aircanada": "https://www.aircanada.com/home/us/en/aco/flights",
        "alaska": "https://www.alaskaair.com",  # Fallback if data missing
        "flyingblue": "https://wwws.airfrance.us/search/advanced",
        "airfrance": "https://wwws.airfrance.us/search/advanced",
        "british": "https://www.britishairways.com/travel/home/public/en_us",
        "virginatlantic": "https://www.virginatlantic.com/en-US",
        "qantas": "https://www.qantas.com/en-us",  # Fallback if data missing
        "jetblue": "https://www.jetblue.com",
        "emirates": "https://www.emirates.com/us/english/book",
        "qatar": "https://www.qatarairways.com/en-us/book.html",
        "singapore": "https://www.singaporeair.com/en_UK/us/home#/book/bookflight",
    }

    return program_urls.get(source, "https://www.google.com/travel/flights")


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


def _store_cash_in_state(
    result: dict,
    tool_context: ToolContext | None,
    flight_request: FlightRequest | None = None,
) -> None:
    """Persist cash flight results into session state for SSE injection & lazy-load."""
    if not tool_context or tool_context.state is None:
        return
    serialized: dict = {}
    for cabin_name, cabin_flights in result.items():
        if isinstance(cabin_flights, list):
            serialized[cabin_name] = [
                f.model_dump() if hasattr(f, "model_dump") else f for f in cabin_flights
            ]
        else:
            serialized[cabin_name] = cabin_flights

    existing_last_cash_search = tool_context.state.get("last_cash_search")
    state_payload = (
        copy.deepcopy(existing_last_cash_search)
        if isinstance(existing_last_cash_search, dict)
        else {}
    )
    state_payload["results"] = serialized

    # Populate compare-cache metadata so compare_award_vs_cash_flights_formatted
    # can hit the 30-minute smart-reuse path instead of re-calling SerpAPI.
    if flight_request is not None:
        state_payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        state_payload["route"] = (
            f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
        )
        state_payload["date"] = flight_request.outbound_date

    tool_context.state["last_cash_search"] = state_payload
    total = sum(len(v) for v in serialized.values() if isinstance(v, list))
    # Expose count as a top-level state key so the planning-agent prompt
    # template can inject it via {last_cash_search_count?}.
    tool_context.state["last_cash_search_count"] = total
    logger.info(f"💾 Stored {total} cash flights in session state (last_cash_search)")


def _store_award_in_state(
    results: list,
    tool_context: ToolContext | None,
    label: str = "",
    flight_request: FlightRequest | FlightDateRangeRequest | None = None,
) -> None:
    """Persist award flight results into session state for SSE injection & lazy-load."""
    if not tool_context or tool_context.state is None:
        return
    serialized = [f.model_dump() if hasattr(f, "model_dump") else f for f in results]

    existing_last_award_search = tool_context.state.get("last_award_search")
    state_payload = (
        copy.deepcopy(existing_last_award_search)
        if isinstance(existing_last_award_search, dict)
        else {}
    )
    state_payload["results"] = serialized

    # Populate compare-cache metadata so compare_award_vs_cash_flights_formatted
    # can hit the 30-minute smart-reuse path instead of re-calling Seats.aero.
    if flight_request is not None:
        state_payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        state_payload["route"] = (
            f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
        )
        # FlightRequest uses outbound_date; FlightDateRangeRequest uses start_date.
        if isinstance(flight_request, FlightRequest):
            state_payload["date"] = flight_request.outbound_date
        else:
            state_payload["date"] = flight_request.start_date

    tool_context.state["last_award_search"] = state_payload
    # Expose count as a top-level state key so the planning-agent prompt
    # template can inject it via {last_award_search_count?}.
    tool_context.state["last_award_search_count"] = len(serialized)
    suffix = f" ({label})" if label else ""
    logger.info(
        f"💾 Stored {len(serialized)} award flights in session state (last_award_search){suffix}"
    )


async def search_cash_flights(
    flight_request: FlightRequest, tool_context: ToolContext | None = None
):
    """Fetch real-time cash flight details from Google Flights using SerpAPI."""
    # ✅ v3: Removed profile_fingerprint variable (never used)
    canonical_params = None
    main_cache_key = None

    if _global_cache is not None:
        canonical_params = canonicalize_search_params(flight_request, "cash")
        main_cache_key = compute_cache_key(
            canonical_params
        )  # ✅ No profile_fingerprint arg

    # INPUT-LEVEL CACHING: Check cache BEFORE making API calls
    if _global_cache is not None:
        # If searching for specific cabin, first check for cached all-cabins result
        if flight_request.cabin_class:
            # Try specific cabin cache first
            cached_result = _global_cache.get(main_cache_key)
            if cached_result is not None:
                logger.info(
                    f"🚀 CACHE HIT: Returning cached specific cabin cash flights: {flight_request.origin} to {flight_request.destination} cabin={flight_request.cabin_class}"
                )
                # 🛡️ DEFENSIVE DEEP COPY: Prevent mutation of cached SUPERSET
                result = copy.deepcopy(cached_result)
                # Apply client-side filters to copied result (max_stops, max_price, preferred_airlines)
                for cabin_name, flights in result.items():
                    if isinstance(flights, list):
                        result[cabin_name] = apply_client_side_filters(
                            flights, flight_request, f"cached {cabin_name}"
                        )
                _store_cash_in_state(result, tool_context, flight_request)
                return result

            # Try to extract from all-cabins cache
            all_cabins_params = canonical_params.copy()
            all_cabins_params["cabin_class"] = None  # All cabins search
            all_cabins_key = compute_cache_key(
                all_cabins_params
            )  # ✅ No profile_fingerprint arg
            all_cabins_result = _global_cache.get(all_cabins_key)
            if all_cabins_result is not None and isinstance(all_cabins_result, dict):
                # Extract the specific cabin from all-cabins result
                target_cabin = flight_request.cabin_class.lower()
                for cabin_name, flights in all_cabins_result.items():
                    if cabin_name.lower() == target_cabin:
                        logger.info(
                            f"🚀 CACHE HIT: Returning cached specific cabin from all-cabins cache: {flight_request.origin} to {flight_request.destination} cabin={flight_request.cabin_class}"
                        )
                        # Cache this specific cabin result for future direct lookups
                        specific_result = {cabin_name: flights}
                        _global_cache.set(main_cache_key, specific_result)
                        # 🛡️ DEFENSIVE DEEP COPY: Prevent mutation of cached SUPERSET
                        result = copy.deepcopy(specific_result)
                        # Apply client-side filters (max_stops, max_price, preferred_airlines)
                        result[cabin_name] = apply_client_side_filters(
                            result[cabin_name], flight_request, "all-cabins extraction"
                        )
                        _store_cash_in_state(result, tool_context, flight_request)
                        return result

                logger.info(
                    f"All-cabins cache found but missing target cabin {flight_request.cabin_class}, will search API"
                )
        else:
            # Searching all cabins - check cache
            cached_result = _global_cache.get(main_cache_key)
            if cached_result is not None:
                logger.info(
                    f"🚀 CACHE HIT: Returning cached all-cabins cash flights: {flight_request.origin} to {flight_request.destination}"
                )
                # 🛡️ DEFENSIVE DEEP COPY: Prevent mutation of cached SUPERSET
                result = copy.deepcopy(cached_result)
                # Apply client-side filters to copied result (max_stops, max_price, preferred_airlines)
                for cabin_name, flights in result.items():
                    if isinstance(flights, list):
                        result[cabin_name] = apply_client_side_filters(
                            flights, flight_request, f"cached {cabin_name}"
                        )
                _store_cash_in_state(result, tool_context, flight_request)
                return result

    # CACHE MISS: Make API calls and transform data
    logger.info(
        f"🔍 CACHE MISS: Searching flights via API: {flight_request.origin} to {flight_request.destination}"
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
        # Our max_stops: 0=nonstop, 1=up to 1 stop, 2=up to 2 stops, None/3+=any
        #
        # CACHE CORRECTNESS: For multi-stop searches (max_stops=1,2,None), always fetch SUPERSET
        # (stops=3 or omit) and filter client-side. This ensures cache consistency when binary
        # direct_filter=False key is shared across different max_stops values.
        if (
            hasattr(flight_request, "max_stops")
            and flight_request.max_stops is not None
        ):
            if flight_request.max_stops == 0:
                params["stops"] = (
                    1  # Nonstop only (separate cache bucket: direct_filter=True)
                )
            else:
                # Multi-stop search: fetch SUPERSET (up to 2 stops) for cache sharing
                # Client-side filter at lines 908-916 will remove excess stops
                params["stops"] = (
                    3  # Up to 2 stops (SUPERSET for all multi-stop variants)
                )
        elif flight_request.is_direct:
            # Backwards compatibility: is_direct=True means nonstop
            params["stops"] = 1
        else:
            # No filter specified: fetch up to 2 stops for cache reuse
            # Note: max_stops=None is treated as "up to 2 stops" for cache efficiency.
            # Users wanting 3+ stop flights are extremely rare and not supported.
            params["stops"] = 3  # Up to 2 stops (matches binary cache bucket)

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

            # NOTE: Client-side filters removed from parsing loop
            # All filters (max_price, preferred_airlines, max_stops) applied after cache retrieval
            # to ensure SUPERSET caching correctness (see post-retrieval filtering after line 1004)

            # Extract ALL flight numbers from all legs (like award search)
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

    result = all_results

    # CACHE TRANSFORMED RESULTS (unfiltered SUPERSET)
    if (
        _global_cache is not None
        and canonical_params is not None
        and main_cache_key is not None
    ):
        if flight_request.cabin_class:
            # Cache specific cabin result
            _global_cache.set(main_cache_key, result)
            logger.info(
                f"💾 Cached specific cabin result: {flight_request.origin} to {flight_request.destination} cabin={flight_request.cabin_class}"
            )
        else:
            # Cache all-cabins result
            _global_cache.set(main_cache_key, result)

            # Also cache individual cabin results for cross-cabin reuse
            for cabin_name, flights in result.items():
                if flights:  # Only cache non-empty results
                    cabin_params = canonical_params.copy()
                    cabin_params["cabin_class"] = cabin_name.lower()
                    cabin_key = compute_cache_key(
                        cabin_params
                    )  # ✅ No profile_fingerprint arg
                    cabin_result = {cabin_name: flights}
                    _global_cache.set(cabin_key, cabin_result)
                    logger.info(
                        f"💾 Cached individual cabin result: {flight_request.origin} to {flight_request.destination} cabin={cabin_name}"
                    )

    # 🛡️ DEFENSIVE DEEP COPY: Prevent mutation of cached SUPERSET
    # Create isolated copy BEFORE filtering to ensure cache stores unfiltered data
    result = copy.deepcopy(result)

    # Apply client-side filters (post-cache for SUPERSET correctness)
    # RATIONALE: Cache stores SUPERSET (stops=3, all prices, all airlines) for all multi-stop searches.
    # Users with different filter values share the same cache, but we filter here after retrieval.
    # This ensures cache correctness: all users get valid supersets, then filter client-side.
    for cabin_name, flights in result.items():
        if isinstance(flights, list):
            result[cabin_name] = apply_client_side_filters(
                flights, flight_request, f"API {cabin_name}"
            )

    _store_cash_in_state(result, tool_context, flight_request)

    return result


async def search_cash_flights_with_count(
    flight_request: FlightRequest, tool_context: ToolContext | None = None
) -> dict:
    """Wrapper around search_cash_flights that returns compact summary metadata.

    The full cash flight results are already persisted to session state by
    search_cash_flights via _store_cash_in_state. Returning them again in the
    tool response makes the payload unnecessarily large for the sub-agent LLM
    (typically 10–15 k tokens for 80 flights). This wrapper therefore returns
    only the total count the LLM needs to write a short intro, avoiding the
    token-scale reliability issues that motivated this wrapper in the first
    place.

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


# class AwardFlightRequest(BaseModel):
#     origin: str
#     destination: str
#     start_date: str
#     end_date: str


class AwardFlightInfo(BaseModel):
    source: str
    airline: list[str]
    mileage_cost: str
    total_taxes: str
    departure: str
    arrival: str
    travel_class: str
    date: str = "N/A"


class AwardFlightDetailedInfo(BaseModel):
    """Detailed award flight information with trip-level data from Seats.aero API.

    Field Classification:
    - **Matching-critical fields** (REQUIRED): flight_number, date, departure, arrival
      Enforced by Pydantic. Seats.aero /trips/{id} API guarantees these fields in response.

    - **Display metadata** (OPTIONAL): departs_at, arrives_at, total_duration
      ISO timestamps and duration for UI display. May have defaults without affecting matching.

    - **Booking metadata**: stops, remaining_seats, availability_id
      Additional flight details for user decision-making.

    - **Hub routing metadata** (OPTIONAL): hub, layover_hours
      Only populated for hub-routed connections (when stops=1 and route uses hub airport).
      Provides valuable UX context like "4.5 hour layover in DOH".

    - **Booking link**: booking_url - Direct link to airline booking page (parameterized for Alaska/Qantas)
    """

    source: str
    airline: list[str]
    mileage_cost: str
    total_taxes: str
    departure: str  # Airport code
    arrival: str  # Airport code
    travel_class: str
    date: str
    flight_number: str  # Required for flight matching (changed from flight_numbers to match FlightInfo and frontend)
    departs_at: str = ""  # ISO timestamp
    arrives_at: str = ""  # ISO timestamp
    total_duration: int = 0  # Minutes
    stops: int = 0
    remaining_seats: int = 0
    availability_id: str = ""  # For reference
    booking_url: str = ""  # Airline booking URL (empty if generation fails)
    hub: str | None = None  # Hub airport code (e.g., "DOH") for hub-routed connections
    layover_hours: float | None = (
        None  # Layover duration in hours (e.g., 4.5) for hub-routed connections
    )


class AwardFlightsSelection(BaseModel):
    """A list of flights from the search."""

    flights: list[
        AwardFlightDetailedInfo
    ]  # Use detailed info to include flight numbers


class AwardFlightSummary(BaseModel):
    """Lean summary returned to planning_agent — zero flight tokens in context.

    The SSE layer captures ALL flights from the raw tool response before any
    agent sees them. planning_agent only needs the count + route label to
    write a short intro. Flight details are loaded lazily via get_flight_context.
    """

    total_found: int  # Total number of flights returned by the search
    search_params: str = ""  # Human-readable label e.g. "SFO→NRT, Jul 20 2026, Economy"


class CashFlightSummary(BaseModel):
    """Lean summary returned to planning_agent for cash flight searches.

    Mirrors AwardFlightSummary — the SSE layer already has the full FlightInfo
    list. planning_agent only needs the count + route label to write a short
    intro. Details are loaded lazily via get_flight_context(search_type="cash").
    """

    total_found: int  # Total number of flights returned by the search
    search_params: str = ""  # Human-readable label e.g. "SFO→NRT, Economy"


class SeatsAeroAPI:
    """Client for Seats.aero Partner API."""

    BASE_URL = "https://seats.aero/partnerapi"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("SEATS_AERO_API_KEY")
        if not self.api_key:
            raise ValueError(
                "SEATS_AERO_API_KEY environment variable not set. Please set it in your .env file."
            )
        self.headers = {
            "accept": "application/json",
            "Partner-Authorization": self.api_key,
        }

    def _get(self, endpoint, params=None):
        """Make GET request to API."""
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.get(url, headers=self.headers, params=params, timeout=30)

        response.raise_for_status()  # Raise HTTPError for bad responses

        return response.json()

    def search(
        self,
        origin,
        destination,
        start_date,
        end_date=None,
        cabin=None,
        source=None,
        only_direct_flights=None,
    ):
        """
        Search for award availability.

        Args:
            origin: Origin airport code (e.g., 'SFO')
            destination: Destination airport code (e.g., 'HND')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to start_date
            cabin: Filter by cabin class ('economy', 'business', 'first')
            source: Filter by program ('united', 'aeroplan', 'alaska', etc.)
            only_direct_flights: If True, includes 'only_direct_flights=true' as an API parameter.
                                Any additional client-side filtering (e.g., on {cabin}Direct fields)
                                is expected to be performed by the calling code.
        """
        params = {
            "origin_airport": origin,
            "destination_airport": destination,
            "start_date": start_date,
            "end_date": end_date or start_date,
            "take": 500,
            "order_by": "lowest_mileage",
            "include_trips": "false",
            "include_filtered": "false",
        }

        if only_direct_flights:
            params["only_direct_flights"] = "true"
        if cabin:
            params["cabin"] = cabin
        if source:
            params["source"] = source

        return self._get("search", params)

    def get_availability(
        self,
        source,
        origin=None,
        destination=None,
        start_date=None,
        end_date=None,
        cursor=None,
    ):
        """
        Get availability for a specific program.

        Args:
            source: Program name ('united', 'aeroplan', 'alaska', etc.)
            origin: Origin airport code
            destination: Destination airport code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            cursor: Pagination cursor
        """
        params = {"source": source}

        if origin:
            params["origin_airport"] = origin
        if destination:
            params["destination_airport"] = destination
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if cursor:
            params["cursor"] = cursor

        return self._get("availability", params)

    def get_routes(self, source=None):
        """Get available routes."""
        params = {}
        if source:
            params["source"] = source
        return self._get("routes", params)

    def get_trip(self, trip_id, include_filtered=False):
        """Get a specific trip by ID."""
        params = {"include_filtered": str(include_filtered).lower()}
        return self._get(f"trips/{trip_id}", params)


def search_award_flights(
    flight_request: FlightRequest, tool_context: ToolContext = None
):
    """Fetch flight details from seats.aero using user's personal API key.

    Always fetches detailed trip info including flight numbers and times for accurate matching.
    This requires additional API calls (up to MAX_TRIP_DETAIL_FETCHES=10) but provides
    complete flight data needed for cash/award comparison.

    Args:
        flight_request: Flight search parameters
        tool_context: ADK tool context for accessing user_id from session state

    Returns:
        List of AwardFlightDetailedInfo objects
    """
    # Sync max_stops with is_direct for backwards compatibility
    if flight_request.max_stops == 0:
        flight_request.is_direct = True

    logger.info(
        f"🔍 search_award_flights called with: origin={flight_request.origin}, destination={flight_request.destination}, is_direct={flight_request.is_direct}, max_stops={flight_request.max_stops}, cabin_class={flight_request.cabin_class}"
    )

    # Apply UI filter defaults to ensure consistent behavior with comparison tool
    apply_ui_filter_defaults(flight_request, tool_context)

    # ✅ v3: Removed profile_fingerprint from cache key (fetch_trip_details removed entirely)
    canonical_params = None
    cache_key = None

    if _global_cache is not None:
        canonical_params = canonicalize_search_params(flight_request, "award")
        cache_key = compute_cache_key(canonical_params)  # ✅ No profile_fingerprint arg
        cached_result = _global_cache.get(cache_key)
        if cached_result is not None:
            logger.info(
                f"🚀 CACHE HIT: Returning cached award flights: {flight_request.origin} to {flight_request.destination}"
            )
            # 🛡️ DEFENSIVE DEEP COPY: Prevent mutation of cached SUPERSET
            # Using copy.deepcopy() ensures all nested objects are duplicated,
            # not just the top-level containers. This is critical because:
            # 1. Filters may modify nested lists like 'airline' field
            # 2. Pydantic objects contain nested structures that need full isolation
            # 3. Shallow copy would leave nested objects as shared references
            cached_result = copy.deepcopy(cached_result)

            # Apply client-side direct flight filter to cached results
            if flight_request.max_stops == 0 or flight_request.is_direct:
                original_count = len(cached_result)
                cached_result = [
                    flight
                    for flight in cached_result
                    if (
                        flight.get("stops", 0)
                        if isinstance(flight, dict)
                        else getattr(flight, "stops", 0)
                    )
                    == 0
                ]
                filtered_count = len(cached_result)
                logger.info(
                    f"🛡️ Applied direct flight filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} indirect flights)"
                )

            # Apply client-side max_points filter to cached results
            if flight_request.max_points > 0:
                original_count = len(cached_result)
                cached_result = [
                    flight
                    for flight in cached_result
                    if (
                        int(flight.get("mileage_cost", 0))
                        if isinstance(flight, dict)
                        else int(getattr(flight, "mileage_cost", 0) or 0)
                    )
                    <= flight_request.max_points
                ]
                filtered_count = len(cached_result)
                logger.info(
                    f"🛡️ Applied max_points filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} flights over {flight_request.max_points} points)"
                )

            # Apply client-side preferred_airlines filter to cached results
            if (
                flight_request.preferred_airlines
                and len(flight_request.preferred_airlines) > 0
            ):
                original_count = len(cached_result)
                preferred_normalized = [
                    normalize_airline_name(a) for a in flight_request.preferred_airlines
                ]
                filtered_result = []
                for flight in cached_result:
                    airline_list = (
                        flight.get("airline", [])
                        if isinstance(flight, dict)
                        else getattr(flight, "airline", [])
                    )
                    if not isinstance(airline_list, list):
                        airline_list = [airline_list] if airline_list else []
                    airline_match = any(
                        normalize_airline_name(airline) in preferred_normalized
                        for airline in airline_list
                    )
                    if airline_match:
                        filtered_result.append(flight)
                cached_result = filtered_result
                filtered_count = len(cached_result)
                logger.info(
                    f"🛡️ Applied preferred_airlines filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} non-preferred airlines)"
                )

            _store_award_in_state(
                cached_result, tool_context, "cache hit", flight_request
            )

            return cached_result

    # CACHE MISS: Make API calls and transform data
    logger.info(
        f"🔍 CACHE MISS: Searching award flights via API: {flight_request.origin} to {flight_request.destination}"
    )

    # Limit trip detail fetches to top results to reduce API load
    trip_fetch_count = 0

    # ✅ NEW: Get user's API key from Firebase
    user_id = None
    api_key = None
    if tool_context and tool_context.state:
        user_id = tool_context.state.get("user_id")
        logger.info(f"🔍 DEBUG: tool_context.state type: {type(tool_context.state)}")
        logger.info(
            f"🔍 DEBUG: tool_context.state has keys: {hasattr(tool_context.state, 'keys')}"
        )
        if hasattr(tool_context.state, "keys") and callable(
            getattr(tool_context.state, "keys", None)
        ):
            try:
                logger.info(
                    f"🔍 DEBUG: tool_context.state keys: {list(tool_context.state.keys())}"
                )
            except (TypeError, AttributeError):
                pass  # Mock object or non-iterable state
        logger.info(f"🔍 DEBUG: user_id from tool_context: {user_id}")

    # 🔒 DEFENSE-IN-DEPTH: Enforce subscription tier at code level (even if LLM bypasses prompt)
    # This ensures free-tier users cannot access award search regardless of how the tool is invoked
    if not check_feature_access("award_search", tool_context):
        logger.warning(
            "⚠️ Award search blocked: User does not have required subscription tier"
        )
        return [
            {
                "error": "🔒 Award flight search requires a Premium or Pro subscription. Please upgrade to unlock award flight searches and find the best deals using your points and miles.",
                "action": "upgrade_subscription",
            }
        ]

    if user_id:
        api_key = get_user_api_key(user_id, "seats_aero")
        logger.info(f"🔍 DEBUG: API key retrieved: {'Yes' if api_key else 'No'}")

    # ✅ NEW: Handle missing API key
    if not api_key:
        # Try environment variable as fallback (for demo/testing)
        api_key = os.getenv("SEATS_AERO_API_KEY")
        if not api_key:
            return [
                {
                    "error": "To search for award flights, please add your Seats.aero API key in Edit Wallet.",
                    "action": "open_edit_wallet",
                }
            ]

    # ✅ MODIFIED: Pass user's API key to SeatsAeroAPI
    try:
        seats_aero_api = SeatsAeroAPI(api_key=api_key)

        # Pass cabin parameter to API for efficient filtering at source
        # This reduces data transfer and ensures we only get relevant results
        # E.g., cabin='economy' returns ~23 direct flights vs cabin=None returning 155+ (all cabins)
        cabin_param = (
            flight_request.cabin_class.lower() if flight_request.cabin_class else None
        )
        api_params = {
            "origin": flight_request.origin,
            "destination": flight_request.destination,
            "start_date": flight_request.outbound_date,
            "end_date": flight_request.outbound_date,
            "cabin": cabin_param,
            "only_direct_flights": flight_request.is_direct,
        }
        logger.info(
            f"🔍 DEBUG: Calling seats_aero_api.search() with params: {api_params}"
        )

        data = seats_aero_api.search(
            origin=flight_request.origin,
            destination=flight_request.destination,
            start_date=flight_request.outbound_date,
            end_date=flight_request.outbound_date,
            cabin=cabin_param,  # Filter at API level for efficiency
            only_direct_flights=flight_request.is_direct,
        )

        # 🔍 DEBUG: Log response summary
        if data and isinstance(data, dict):
            data_list = data.get("data", [])
            logger.info(f"🔍 DEBUG: API returned {len(data_list)} availability records")
            if len(data_list) > 0:
                # Log first record structure for debugging
                first_record = data_list[0]
                logger.info(
                    f"🔍 DEBUG: First record ID={first_record.get('ID')}, Source={first_record.get('Source')}, "
                    f"YAvailable={first_record.get('YAvailable')}, YRemainingSeats={first_record.get('YRemainingSeats')}"
                )

        # ✅ NEW: Update last_used timestamp on success
        if user_id and data is not None:
            update_user_api_key_last_used(user_id, "seats_aero")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 or e.response.status_code == 403:
            return [
                {
                    "error": "Your Seats.aero API key appears to be invalid. Please update it in Edit Wallet.",
                    "action": "open_edit_wallet",
                }
            ]
        logger.error(f"Seats.aero API error: {e}")
        return []
    except Exception as e:
        logger.error(f"Error searching award flights: {e}")
        return []

    if data is None:
        result = []
    else:
        # Check if the top-level 'data' key exists and is a list
        if (
            not isinstance(data, dict)
            or "data" not in data
            or not isinstance(data["data"], list)
        ):
            logger.error(
                "Error: 'data' key not found or is not a list in the JSON response."
            )
            result = []
        else:
            extracted_results = []

            for idx, item in enumerate(data["data"], 1):
                # Extract general route information
                route_info = item.get("Route", {})
                origin = route_info.get("OriginAirport", "N/A")
                destination = route_info.get("DestinationAirport", "N/A")
                flight_date = item.get("Date", "N/A")
                source = item.get("Source", "N/A")
                availability_id = item.get("ID", "")

                if DEBUG_LOGGING_ENABLED:
                    logger.info(
                        f"🔄 Processing availability record [{idx}/{len(data['data'])}]: source={source}, id={availability_id}"
                    )

                # Define the cabin classes and their respective keys
                cabin_classes = {
                    "Y": "Economy",
                    "W": "Premium Economy",
                    "J": "Business",
                    "F": "First",
                }

                # 🐛 BUG FIX: If cabin class is specified, only process THAT cabin, not all 4!
                # The old code looped through all cabins even when user specified one, causing:
                # - Unnecessary API calls
                # - Complex break/continue logic that skips valid flights
                # - Premature exits from the loop
                if flight_request.cabin_class:
                    # Find the cabin code for the requested cabin
                    target_cabin_code = None
                    target_cabin_name = None
                    for code, name in cabin_classes.items():
                        if name.lower() == flight_request.cabin_class.lower():
                            target_cabin_code = code
                            target_cabin_name = name
                            break

                    if target_cabin_code:
                        # Process ONLY the requested cabin
                        cabin_classes = {target_cabin_code: target_cabin_name}
                        logger.info(
                            f"🎯 Cabin filter applied: Only processing {target_cabin_name} (code={target_cabin_code})"
                        )
                    # If no match found, keep all cabins (fallback to old behavior)
                else:
                    logger.info("🎯 No cabin filter: Processing all 4 cabin classes")

                # Iterate through each cabin class to extract its specific details
                for code, name in cabin_classes.items():
                    is_available = item.get(f"{code}Available", False)
                    item.get(f"{code}RemainingSeats", 0)
                    mileage_cost = item.get(f"{code}MileageCostRaw", 0)
                    total_taxes = item.get(f"{code}TotalTaxesRaw", 0)
                    taxes_currency = item.get("TaxesCurrency", "N/A")
                    airlines = item.get(f"{code}Airlines", "N/A")

                    # Filter by booking indicators (available flag OR costs)
                    # NOTE: We do NOT filter by remaining_seats at this level because:
                    # 1. Search endpoint shows aggregate seat counts across programs
                    # 2. Trip endpoint (line 1082) has accurate per-flight seat counts
                    # 3. Same flight can show 0 seats in one program but >0 seats in another
                    # Pre-filtering here would incorrectly exclude valid flights
                    if is_available or mileage_cost > 0 or total_taxes > 0:
                        # No need to filter by cabin class here anymore - we already filtered the loop!

                        # Filter by direct flights if specified
                        is_direct_flight = item.get(f"{code}Direct", False)
                        logger.info(
                            f"Direct flight check: availability_id={availability_id}, cabin={name}, is_direct_flight={is_direct_flight}, flight_request.is_direct={flight_request.is_direct}"
                        )
                        if flight_request.is_direct and not is_direct_flight:
                            logger.info(
                                f"Skipping indirect flight: availability_id={availability_id}, cabin={name}"
                            )
                            continue

                        # ✅ REMOVED PRE-CACHE FILTERS: max_points and preferred_airlines
                        # These are now applied POST-RETRIEVAL to maintain SUPERSET caching
                        # Cache key (v3) excludes these fields for maximum cache sharing
                        # Filtering happens after line 1794 cache.set() to prevent pollution

                        # Always fetch trip details for accurate matching (up to MAX_TRIP_DETAIL_FETCHES limit)
                        if availability_id:
                            if trip_fetch_count >= MAX_TRIP_DETAIL_FETCHES:
                                logger.info(
                                    f"⏭️ Skipping trip fetch for {availability_id} (limit of {MAX_TRIP_DETAIL_FETCHES} reached)"
                                )
                                # Skip this availability record (no summary fallback)
                                continue
                            else:
                                # Fetch detailed trip information with retry logic
                                if DEBUG_LOGGING_ENABLED:
                                    logger.info(
                                        f"🔍 Attempting to fetch trip details: availability_id={availability_id}, cabin={name} (fetch #{trip_fetch_count + 1})"
                                    )

                                trip_data = retry_api_call(
                                    seats_aero_api.get_trip, availability_id
                                )

                                if DEBUG_LOGGING_ENABLED:
                                    logger.info(
                                        f"📦 Got trip_data: {bool(trip_data)}, is_dict: {isinstance(trip_data, dict)}"
                                    )

                                if trip_data and isinstance(trip_data, dict):
                                    # Trip API returns {"data": [...], "carriers": {}, ...}
                                    # Need to extract from the data array
                                    trips = trip_data.get("data", [])
                                    if DEBUG_LOGGING_ENABLED:
                                        logger.info(
                                            f"📋 Found {len(trips)} trips in response"
                                        )

                                    # Find trip that matches the current cabin class
                                    target_cabin = normalize_cabin_name(name)
                                    found_matching_cabin = False

                                    if DEBUG_LOGGING_ENABLED:
                                        logger.info(
                                            f"Available cabins in trip {availability_id}: {[trip.get('Cabin', '') for trip in trips]}"
                                        )
                                    for trip in trips:
                                        trip_cabin = trip.get("Cabin", "")
                                        trip_cabin_normalized = normalize_cabin_name(
                                            trip_cabin
                                        )
                                        if DEBUG_LOGGING_ENABLED:
                                            logger.debug(
                                                f"Comparing '{trip_cabin_normalized}' ({trip_cabin_normalized!r}) == '{target_cabin}' ({target_cabin!r}) = {trip_cabin_normalized == target_cabin}"
                                            )
                                            logger.info(
                                                f"🔍 Checking trip cabin: '{trip_cabin}' (normalized: '{trip_cabin_normalized}') vs target: '{target_cabin}' for availability {availability_id}"
                                            )
                                            logger.info(
                                                f"   Repr trip: {trip_cabin_normalized!r}, Repr target: {target_cabin!r}, Equal: {trip_cabin_normalized == target_cabin}"
                                            )
                                        if trip_cabin_normalized == target_cabin:
                                            if DEBUG_LOGGING_ENABLED:
                                                logger.debug(
                                                    f"Matched cabin for {trip.get('FlightNumbers', 'unknown')}"
                                                )
                                            # Get trip details
                                            trip_remaining_seats = trip.get(
                                                "RemainingSeats", 0
                                            )
                                            # Normalize flight numbers: API can return string or list (e.g., ["QR714"])
                                            flight_numbers = normalize_flight_numbers(
                                                trip.get("FlightNumbers")
                                            )
                                            if DEBUG_LOGGING_ENABLED:
                                                logger.info(
                                                    f"🎯 MATCH FOUND! Flight {flight_numbers} has {trip_remaining_seats} seats in cabin {trip_cabin}"
                                                )

                                            # Filter out unbookable program entries (0 seats)
                                            # The same physical flight may still appear in other programs with >0 seats.
                                            # Those bookable variants will be captured and shown to the user.
                                            # This improves UX by not showing "AA44 in American (0 seats)" when
                                            # we also show "AA44 in Alaska (9 seats)" - user only sees bookable options.
                                            if trip_remaining_seats == 0:
                                                if DEBUG_LOGGING_ENABLED:
                                                    logger.info(
                                                        f"🚫 Skipping {flight_numbers} from {source} (0 seats) - may be available in other programs"
                                                    )
                                                continue

                                            departs_at = trip.get("DepartsAt", "")
                                            arrives_at = trip.get("ArrivesAt", "")
                                            total_duration = trip.get(
                                                "TotalDuration", 0
                                            )
                                            stops = trip.get("Stops", 0)
                                            if DEBUG_LOGGING_ENABLED:
                                                logger.debug(
                                                    f"Flight {flight_numbers} has {stops} stops"
                                                )

                                            # Generate booking URL
                                            booking_url = generate_award_booking_url(
                                                {
                                                    "source": source,
                                                    "origin": origin,
                                                    "destination": destination,
                                                    "date": flight_date,
                                                    "cabin": name.lower(),
                                                }
                                            )

                                            award_flight_info = AwardFlightDetailedInfo(
                                                source=source,
                                                airline=airlines.split(", ")
                                                if airlines != "N/A"
                                                else [],
                                                mileage_cost=str(mileage_cost),
                                                total_taxes=f"{total_taxes / 100:.2f} {taxes_currency}"
                                                if taxes_currency != "N/A"
                                                else f"{total_taxes / 100:.2f}",
                                                departure=origin,
                                                arrival=destination,
                                                travel_class=name,
                                                date=flight_date,
                                                flight_number=flight_numbers,
                                                departs_at=departs_at,
                                                arrives_at=arrives_at,
                                                total_duration=total_duration,
                                                stops=stops,
                                                remaining_seats=trip_remaining_seats,
                                                availability_id=availability_id,
                                                booking_url=booking_url,
                                            )
                                            extracted_results.append(award_flight_info)
                                            if DEBUG_LOGGING_ENABLED:
                                                logger.debug(
                                                    f"✅ ADDED {flight_numbers} from {source}"
                                                )
                                                logger.info(
                                                    f"✅ Added detailed trip: {flight_numbers} ({name}, cabin={trip_cabin})"
                                                )
                                            trip_fetch_count += 1
                                            found_matching_cabin = True
                                            # 🐛 BUG FIX: DO NOT break here! Same availability record can have MULTIPLE direct flights!
                                            # Example: "flyingblue" program might have AF1, AF3, AF5, AF7 - all direct Economy flights
                                            # If we break after AF1, we miss AF3, AF5, AF7!
                                            # REMOVED: break  # Found matching cabin, stop searching trips

                                    # Check if we found a matching cabin
                                    if found_matching_cabin:
                                        # Successfully added detailed trip, skip summary data
                                        break  # Safe to break: cabin_classes already filtered to 1 item at line 1060
                                    else:
                                        # No matching cabin found in trip details
                                        # Fall through to use summary data from search endpoint
                                        if DEBUG_LOGGING_ENABLED:
                                            logger.warning(
                                                f"⚠️ No matching cabin found for target '{target_cabin}' in trip {availability_id}. Available normalized cabins: {[normalize_cabin_name(trip.get('Cabin', '')) for trip in trips]}"
                                            )
                                        # Fall through to summary data below (don't continue)

                        # Only add summary data if we haven't already added detailed trip data
                        # if not added_detailed_trip_for_this_availability:
                        #     # Summary data (default or fallback)
                        #     award_flight_info = AwardFlightInfo(
                        #         source=source,
                        #         airline=airlines.split(', ') if airlines != "N/A" else [],
                        #         mileage_cost=str(mileage_cost),
                        #         total_taxes=f"{total_taxes / 100:.2f} {taxes_currency}" if taxes_currency != "N/A" else f"{total_taxes / 100:.2f}",
                        #         departure=origin,
                        #         arrival=destination,
                        #         travel_class=name,
                        #         date=flight_date
                        #     )
                        #     extracted_results.append(award_flight_info)

            result = extracted_results

    # 🔄 HUB ROUTING: Fallback for ultra-uncommon routes not cached by Seats.aero
    # Only activates when Seats.aero returns completely empty results AND route is in hub index
    # DESIGN: Same-airline connections only for simpler booking and better user experience
    if not result and not flight_request.is_direct and flight_request.max_stops != 0:
        logger.info(
            f"🔄 Seats.aero returned no results for {flight_request.origin} → {flight_request.destination}. Checking if this ultra-uncommon route has hub routing available..."
        )

        try:
            # Create HubRouter instance with the same API client (lazy import — not used in cash-flight eval)
            from travel_concierge.tools.hub_router import HubRouter  # noqa: PLC0415
            hub_router = HubRouter(seats_aero_api)

            # Find hub routes (only works for routes in pre-computed hub index)
            hub_results = hub_router.find_routes(
                origin=flight_request.origin,
                destination=flight_request.destination,
                date=flight_request.outbound_date,
                cabin_class=flight_request.cabin_class,
            )

            if hub_results:
                # FILTER: Only same-airline connections (Phase 3 design decision)
                # This provides cleaner UX and simpler booking process
                logger.info(
                    f"✅ Found {len(hub_results)} hub connection options for ultra-uncommon route"
                )
                logger.info(
                    f"🔍 Hub results same_airline status: {[(r.get('hub'), r.get('same_airline')) for r in hub_results]}"
                )

                # Filter for same-airline connections only
                same_airline_results = [
                    r for r in hub_results if r.get("same_airline", False)
                ]

                if same_airline_results:
                    logger.info(
                        f"✅ Processing {len(same_airline_results)} same-airline hub connection options"
                    )

                    # Convert hub results to award flight format
                    for hub_option in same_airline_results:
                        # Extract actual airline name (guaranteed same for both legs)
                        trip1 = hub_option.get("trip1", {})
                        trip2 = hub_option.get("trip2", {})
                        avail1 = hub_option.get("avail1", {})
                        avail2 = hub_option.get("avail2", {})

                        airline_code = trip1.get("Airline", "")
                        airline_name = trip1.get(
                            "Carriers", airline_code
                        )  # Use Carriers if available, fallback to code

                        # Extract program source (hub_router already ensured both legs have same source)
                        source = avail1.get(
                            "Source", f"hub_{hub_option['hub'].lower()}"
                        )

                        # Get cabin class for tax and seat extraction
                        # Normalize cabin name to properly capitalized format (e.g., "economy" -> "Economy")
                        cabin_code_map = {
                            "economy": "Y",
                            "premium economy": "W",
                            "business": "J",
                            "first": "F",
                        }
                        cabin_name_map = {
                            "economy": "Economy",
                            "premium economy": "Premium Economy",
                            "business": "Business",
                            "first": "First",
                        }
                        cabin_input = (flight_request.cabin_class or "Economy").lower()
                        cabin = cabin_name_map.get(
                            cabin_input, "Economy"
                        )  # Properly capitalized for display
                        cabin_code = cabin_code_map.get(cabin_input, "Y")

                        # Extract and sum taxes from availability records (NOT trip data)
                        # Taxes are in cabin-specific fields like "YTotalTaxesRaw", "JTotalTaxesRaw"
                        # NOTE: API can return tax values as strings - coerce to int before arithmetic
                        tax1_raw = avail1.get(f"{cabin_code}TotalTaxesRaw", 0) or 0
                        tax2_raw = avail2.get(f"{cabin_code}TotalTaxesRaw", 0) or 0
                        # Safe numeric coercion: handle both string and numeric types (including "120.50")
                        tax1_raw = safe_int_coerce(tax1_raw)
                        tax2_raw = safe_int_coerce(tax2_raw)
                        total_taxes_raw = tax1_raw + tax2_raw
                        taxes_currency = (
                            avail1.get("TaxesCurrency")
                            or avail2.get("TaxesCurrency")
                            or "USD"
                        )

                        # Format taxes (raw values are in cents)
                        total_taxes = (
                            f"{total_taxes_raw / 100:.2f} {taxes_currency}"
                            if taxes_currency
                            else f"{total_taxes_raw / 100:.2f}"
                        )

                        # Extract cabin-specific remaining seats from availability records
                        # This ensures consistency with validation logic in hub_router.py (lines 351-359)
                        # which uses cabin-specific fields like YRemainingSeats, JRemainingSeats
                        # NOTE: API can return seat counts as strings - coerce to int before comparison
                        seats1 = avail1.get(f"{cabin_code}RemainingSeats", 0) or 0
                        seats2 = avail2.get(f"{cabin_code}RemainingSeats", 0) or 0
                        # Safe numeric coercion: handle both string and numeric types (including "9.0")
                        seats1 = safe_int_coerce(seats1)
                        seats2 = safe_int_coerce(seats2)
                        min_remaining_seats = min(seats1, seats2)

                        # Generate booking URL (same as common routes)
                        booking_url = generate_award_booking_url(
                            {
                                "source": source,
                                "origin": flight_request.origin,
                                "destination": flight_request.destination,
                                "date": flight_request.outbound_date,
                                "cabin": cabin.lower(),
                            }
                        )

                        # Create AwardFlightDetailedInfo object (same as common routes)
                        # Populate hub metadata for UX display (e.g., "4.5 hour layover in DOH")
                        # Normalize flight numbers: API can return string or list (e.g., ["QR714"])
                        leg1_flights = normalize_flight_numbers(
                            trip1.get("FlightNumbers")
                        )
                        leg2_flights = normalize_flight_numbers(
                            trip2.get("FlightNumbers")
                        )
                        hub_flight = AwardFlightDetailedInfo(
                            source=source,  # Use actual program source from API (for hyperlinks)
                            airline=[airline_name]
                            if airline_name
                            else ["Multiple"],  # List as expected by schema
                            mileage_cost=str(hub_option["total_points"]),
                            total_taxes=total_taxes,  # Sum of both legs' taxes
                            departure=flight_request.origin,
                            arrival=flight_request.destination,
                            travel_class=cabin,
                            date=flight_request.outbound_date,
                            flight_number=f"{leg1_flights}, {leg2_flights}",
                            departs_at=trip1.get("DepartsAt", ""),
                            arrives_at=trip2.get("ArrivesAt", ""),
                            total_duration=int(
                                hub_option.get("total_duration_hours", 0) * 60
                            ),  # Convert to minutes, ensure int
                            stops=1,  # Hub connections are 1-stop
                            remaining_seats=min_remaining_seats,  # Cabin-specific seats from availability records
                            availability_id=f"hub_{hub_option['hub']}_{trip1.get('ID', '')}_{trip2.get('ID', '')}",
                            booking_url=booking_url,
                            hub=hub_option.get("hub"),  # Hub airport code (e.g., "DOH")
                            layover_hours=hub_option.get(
                                "layover_hours"
                            ),  # Layover duration (e.g., 4.5)
                        )
                        result.append(hub_flight)

                    logger.info(
                        f"🔄 Added {len(same_airline_results)} same-airline hub connection(s)"
                    )
                else:
                    logger.info(
                        f"ℹ️ Hub routing found {len(hub_results)} options but none with same-airline connections"
                    )
            else:
                logger.info(
                    f"ℹ️ No hub routing available for {flight_request.origin} → {flight_request.destination} (route not in ultra-uncommon hub index)"
                )

        except Exception as e:
            logger.warning(f"🔄 Hub routing failed: {e}")
            # Continue with empty results - don't let hub routing failures break the main search

    # CACHE FINAL RESULTS (after hub routing)
    # This ensures we cache the complete result including any hub connections
    # Note: We cache all results including empty ones, since even empty results
    # indicate "we checked hub routing and found nothing" which saves re-computation
    if (
        _global_cache is not None
        and canonical_params is not None
        and cache_key is not None
    ):
        _global_cache.set(cache_key, result)
        result_summary = (
            f"{len(result)} flights"
            if result
            else "empty (no direct or hub routes found)"
        )
        logger.info(
            f"💾 Cached final award search results: {flight_request.origin} to {flight_request.destination} ({result_summary})"
        )

    # Apply client-side filters (POST-CACHE to prevent pollution)
    # RATIONALE: Cache stores unfiltered SUPERSET for maximum sharing.
    # Users with different filter values share the same cache, then filter after retrieval.
    # This matches the cash search pattern (search_cash_flights lines 1104-1136).

    # Filter by direct flights if requested
    if flight_request.max_stops == 0 or flight_request.is_direct:
        original_count = len(result)
        result = [
            flight
            for flight in result
            if (
                flight.get("stops", 0)
                if isinstance(flight, dict)
                else getattr(flight, "stops", 0)
            )
            == 0
        ]
        filtered_count = len(result)
        logger.info(
            f"🛡️ Applied direct flight filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} indirect flights)"
        )

    # Filter by max_points if requested
    if flight_request.max_points > 0:
        original_count = len(result)
        result = [
            flight
            for flight in result
            if (
                int(flight.get("mileage_cost", 0))
                if isinstance(flight, dict)
                else int(getattr(flight, "mileage_cost", 0) or 0)
            )
            <= flight_request.max_points
        ]
        filtered_count = len(result)
        logger.info(
            f"🛡️ Applied max_points filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} flights over {flight_request.max_points} points)"
        )

    # Filter by preferred_airlines if requested
    if flight_request.preferred_airlines and len(flight_request.preferred_airlines) > 0:
        original_count = len(result)
        preferred_normalized = [
            normalize_airline_name(a) for a in flight_request.preferred_airlines
        ]
        filtered_result = []
        for flight in result:
            airline_list = (
                flight.get("airline", [])
                if isinstance(flight, dict)
                else getattr(flight, "airline", [])
            )
            if not isinstance(airline_list, list):
                airline_list = [airline_list] if airline_list else []
            airline_match = any(
                normalize_airline_name(airline) in preferred_normalized
                for airline in airline_list
            )
            if airline_match:
                filtered_result.append(flight)
        result = filtered_result
        filtered_count = len(result)
        logger.info(
            f"🛡️ Applied preferred_airlines filter: {original_count} -> {filtered_count} flights (removed {original_count - filtered_count} non-preferred airlines)"
        )

    _store_award_in_state(result, tool_context, flight_request=flight_request)

    return result


def search_award_flights_with_count(
    flight_request: FlightRequest, tool_context: ToolContext | None = None
) -> dict:
    """Wrapper around search_award_flights that returns compact summary metadata.

    The full award flight results are already persisted to session state by
    search_award_flights via _store_award_in_state. Returning them again in the
    tool response makes the payload unnecessarily large for the sub-agent LLM
    (typically 10–15 k tokens for 80 flights). This wrapper therefore returns
    only the total count the LLM needs to populate AwardFlightSummary.total_found,
    avoiding the token-scale reliability issues that motivated this wrapper.

    Args:
        flight_request: Flight search parameters
        tool_context: ADK tool context for accessing user_id from session state

    Returns:
        Dict with 'total_count' key
    """
    flights = search_award_flights(flight_request, tool_context)
    return {"total_count": len(flights)}


def merge_award_and_cash_flights(
    award_flights: list[AwardFlightInfo | AwardFlightDetailedInfo | dict],
    cash_flights: dict,
) -> list[dict]:
    """Merge award and cash flight results with value comparison.

    Args:
        award_flights: List of award flight objects from search_award_flights() or dicts from cache
        cash_flights: Dict of cabin class -> list of cash flights from search_cash_flights()
                     e.g., {"Economy": [...], "Business": [...]}

    Returns:
        List of merged flight options with value analysis

    Note:
        **Field Requirements & Data Quality Guarantee:**

        Matching-critical fields (flight_number, date, origin, destination) are REQUIRED by Pydantic.
        These fields are populated by SerpAPI and Seats.aero APIs which provide 100% coverage:

        - SerpAPI (cash flights): Extracts origin/destination from departure_airport.id and
          arrival_airport.id fields, which are always present in flight leg data. Date comes
          from user's search parameters. Flight numbers extracted from all legs.

        - Seats.aero (award flights): Origin/destination from Route.OriginAirport and
          Route.DestinationAirport (required by API). Date from Date field (required by API).
          Flight numbers from /trips/{id} endpoint FlightNumbers field.

        Display fields (depart_time, arrive_time, duration_minutes) are OPTIONAL because:
        - They are metadata for UI presentation only
        - Not used in matching algorithm (see lines 1300-1312)
        - May be missing from some API responses without affecting match quality

        **Why no null checks?** Both APIs guarantee the required fields. If they're missing,
        Pydantic raises ValidationError at parsing time (lines 724, 1182), preventing invalid
        data from reaching this function. This fail-fast validation eliminates the need for
        defensive null checks in matching logic.
    """

    def get_award_attr(award, attr):
        """Get attribute from award flight, handling both objects and dicts."""
        if isinstance(award, dict):
            return award.get(attr)
        else:
            return getattr(award, attr, None)

    def get_cash_attr(cash, attr):
        """Get attribute from cash flight, handling both objects and dicts."""
        if isinstance(cash, dict):
            return cash.get(attr)
        else:
            return getattr(cash, attr, None)

    merged = []
    matched_cash_flights = set()  # Track which cash flights we've matched

    logger.info(
        f"🔀 MERGE: Processing {len(award_flights)} award flights, types: {[type(award).__name__ for award in award_flights[:3]]}"
    )

    # Build index: (flight_number, date, route) → list of (cabin_name, cash_flight) tuples
    # This enables O(1) lookup with full context validation (flight#, date, route)
    # Critical for date range searches where same flight# appears on multiple dates
    cash_by_key = defaultdict(list)
    for cabin_name, cash_cabin_flights in cash_flights.items():
        for cash in cash_cabin_flights:
            flight_num = get_cash_attr(cash, "flight_number")
            flight_num = (flight_num or "").strip().upper()
            if flight_num:
                # Use normalized fields directly - no parsing needed!
                cash_date = get_cash_attr(cash, "date")
                cash_origin = get_cash_attr(cash, "origin")
                cash_destination = get_cash_attr(cash, "destination")
                cash_route = f"{cash_origin}-{cash_destination}"

                # Key includes flight number, date, AND route to prevent false matches
                key = (flight_num, cash_date, cash_route)
                cash_by_key[key].append((cabin_name, cash))

    logger.info(
        f"📇 Built index with {len(cash_by_key)} unique (flight#, date, route) combinations"
    )

    for award in award_flights:
        # Extract commonly-used attributes once to avoid repeated function calls
        award_cabin = get_award_attr(award, "travel_class")
        award_departure = get_award_attr(award, "departure")
        award_arrival = get_award_attr(award, "arrival")
        award_date = get_award_attr(award, "date")
        award_airline = get_award_attr(award, "airline")
        award_source = get_award_attr(award, "source")
        award_mileage_cost = get_award_attr(award, "mileage_cost")
        award_total_taxes = get_award_attr(award, "total_taxes")
        award_flight_number = get_award_attr(award, "flight_number")
        award_departs_at = get_award_attr(award, "departs_at")
        award_arrives_at = get_award_attr(award, "arrives_at")
        award_total_duration = get_award_attr(award, "total_duration")
        award_stops = get_award_attr(award, "stops")
        award_remaining_seats = get_award_attr(award, "remaining_seats")

        # Validate required fields
        if award_cabin is None:
            logger.warning(f"Award flight missing travel_class: {award}")
            continue

        # Normalize flight number once
        award_flight_nums_str = (award_flight_number or "").strip().upper()

        # Log award flight details for debugging
        award_info = (
            f"{award_departure}-{award_arrival} on {award_date} ({award_cabin})"
        )
        if award_flight_nums_str:
            award_info += f" flights=[{award_flight_nums_str}]"
        logger.info(f"🎯 Matching award flight: {award_info}")

        # O(1) lookup in index with full context validation (flight#, date, route)
        matched_cash = None
        if award_flight_nums_str:
            # Build lookup key with flight number, date, and route
            award_route = f"{award_departure}-{award_arrival}"
            key = (award_flight_nums_str, award_date, award_route)

            if key in cash_by_key:
                # Found exact match: same flight number, date, AND route
                for cabin_name, cash in cash_by_key[key]:
                    if cabin_name == award_cabin:
                        logger.info(
                            f"✅ EXACT FLIGHT MATCH: {award_flight_nums_str} on {award_date} {award_route}"
                        )
                        matched_cash = cash
                        break

        # Create merged result if we found a match
        if matched_cash:
            matched_cash_flights.add(id(matched_cash))
            match_type = "exact"  # Flight number matched - same physical flight

            # Calculate value comparison
            try:
                cash_price = float(get_cash_attr(matched_cash, "price"))
                points = float(award_mileage_cost)
                taxes_str = award_total_taxes.split()[0]  # "57.00 USD" -> "57.00"
                taxes = float(taxes_str)

                # Calculate cents per point (CPP)
                cpp_value = ((cash_price - taxes) / points * 100) if points > 0 else 0

                # Resolve display name: award flights carry IATA codes (e.g. ['AA', 'AT']).
                # Use the first (marketing) carrier only, then resolve to a human-readable name.
                _award_iata = (
                    award_airline[0]
                    if isinstance(award_airline, list) and award_airline
                    else award_airline
                ) or ""
                merged.append(
                    {
                        "match_type": match_type,
                        "match_score": 100,
                        "route": f"{award_departure}-{award_arrival}",
                        "date": award_date,
                        "airline": iata_to_display_name(_award_iata),
                        "cabin": award_cabin,
                        # Award option
                        "award": {
                            "points": points,
                            "taxes": taxes,
                            "program": get_program_display_name(award_source),
                            "airlines": award_airline,
                            "flight_numbers": award_flight_number or "",
                            "departs_at": award_departs_at or "",
                            "arrives_at": award_arrives_at or "",
                            "total_duration": award_total_duration or 0,
                            "stops": award_stops or 0,
                            "remaining_seats": award_remaining_seats or 0,
                            "booking_url": get_award_attr(award, "booking_url") or "",
                        },
                        # Cash option
                        "cash": {
                            "price": cash_price,
                            "flight_number": get_cash_attr(
                                matched_cash, "flight_number"
                            )
                            or "",
                            "departure": get_cash_attr(matched_cash, "departure"),
                            "arrival": get_cash_attr(matched_cash, "arrival"),
                            "depart_time": get_cash_attr(matched_cash, "depart_time")
                            or "",
                            "arrive_time": get_cash_attr(matched_cash, "arrive_time")
                            or "",
                            "duration": get_cash_attr(matched_cash, "duration"),
                            "airline_logo": get_cash_attr(matched_cash, "airline_logo")
                            or "",
                            "booking_url": get_cash_attr(matched_cash, "booking_url")
                            or "",
                        },
                        # Value comparison
                        "value_analysis": {
                            "cpp": round(cpp_value, 2),
                            "recommendation": "USE_POINTS"
                            if cpp_value >= 1.5
                            else "PAY_CASH",
                            "savings": round(
                                cash_price - taxes
                                if cpp_value >= 1.5
                                else taxes - cash_price,
                                2,
                            ),
                            "reason": f"Redeeming points gets you {cpp_value:.2f}¢ per point"
                            if cpp_value >= 1.5
                            else f"Only {cpp_value:.2f}¢ per point - below recommended 1.5¢ threshold",
                        },
                    }
                )
                logger.info(
                    f"✅ Matched: {award_departure}-{award_arrival} {award_cabin} (cpp: {cpp_value:.2f}¢/pt)"
                )
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning(f"Failed to calculate value for match: {e}")
        else:
            # Award-only flight (no cash match)
            try:
                points = float(award_mileage_cost)
                taxes_str = award_total_taxes.split()[0]
                taxes = float(taxes_str)

                # Resolve display name: same logic as matched block above.
                _award_iata = (
                    award_airline[0]
                    if isinstance(award_airline, list) and award_airline
                    else award_airline
                ) or ""
                merged.append(
                    {
                        "match_type": "award_only",
                        "route": f"{award_departure}-{award_arrival}",
                        "date": award_date,
                        "airline": iata_to_display_name(_award_iata),
                        "cabin": award_cabin,
                        "award": {
                            "points": points,
                            "taxes": taxes,
                            "program": get_program_display_name(award_source),
                            "airlines": award_airline,
                            "flight_numbers": award_flight_number or "",
                            "total_duration": award_total_duration or 0,
                            "stops": award_stops or 0,
                            "booking_url": get_award_attr(award, "booking_url") or "",
                        },
                        "cash": None,
                        "value_analysis": {
                            "recommendation": "USE_POINTS",
                            "reason": "Award space available, no cash comparison found",
                        },
                    }
                )
            except (ValueError, TypeError, AttributeError):
                pass

    # Add cash-only flights (no award space available)
    for cabin_name, cash_cabin_flights in cash_flights.items():
        for cash in cash_cabin_flights:
            if id(cash) not in matched_cash_flights:
                try:
                    # Use normalized fields directly - no parsing needed!
                    cash_origin = get_cash_attr(cash, "origin")
                    cash_dest = get_cash_attr(cash, "destination")
                    cash_date = get_cash_attr(cash, "date")

                    cash_price = float(get_cash_attr(cash, "price"))

                    merged.append(
                        {
                            "match_type": "cash_only",
                            "route": f"{cash_origin}-{cash_dest}",
                            "date": cash_date,
                            "airline": get_cash_attr(cash, "airline"),
                            "cabin": cabin_name,
                            "award": None,
                            "cash": {
                                "price": cash_price,
                                "flight_number": get_cash_attr(cash, "flight_number")
                                or "",
                                "departure": get_cash_attr(cash, "departure"),
                                "arrival": get_cash_attr(cash, "arrival"),
                                "depart_time": get_cash_attr(cash, "depart_time") or "",
                                "arrive_time": get_cash_attr(cash, "arrive_time") or "",
                                "duration": get_cash_attr(cash, "duration"),
                                "booking_url": get_cash_attr(cash, "booking_url") or "",
                            },
                            "value_analysis": {
                                "recommendation": "PAY_CASH",
                                "reason": "No award availability for this flight",
                            },
                        }
                    )
                except (ValueError, TypeError, AttributeError, IndexError):
                    pass

    return merged


async def compare_award_vs_cash_flights(flight_request: FlightRequest):
    """
    Search for both award and cash flights, then provide value comparison.

    ⚠️ TESTING ONLY: This function is NOT used in production.
    Use compare_award_vs_cash_flights_formatted() instead for UI-ready output.
    This version returns raw data structures for testing and development purposes.

    This function automatically:
    1. Searches for award flights with detailed trip information (including flight numbers) ✅
    2. Searches for cash flights across all cabin classes
    3. Matches award and cash flights by route, date, airline, and flight number
    4. Calculates cents-per-point (CPP) value
    5. Recommends whether to use points or pay cash

    Args:
        flight_request: FlightRequest with origin, destination, and outbound_date

    Returns:
        List of merged flight options with value analysis
    """
    logger.info(
        f"Comparing award vs cash flights: {flight_request.origin} to {flight_request.destination}"
    )

    # Search award flights with detailed trip information for accurate matching
    # ✅ FIXED: Now fetches trip details to get flight numbers
    award_flights = search_award_flights(flight_request)
    logger.info(f"📊 Fetched {len(award_flights)} award flights with trip details")

    # Search cash flights across all cabin classes
    cash_flights_dict = await search_cash_flights(flight_request)
    total_cash = sum(len(flights) for flights in cash_flights_dict.values())
    logger.info(f"💵 Fetched {total_cash} cash flights across all cabin classes")

    # Merge and analyze value
    comparison = merge_award_and_cash_flights(award_flights, cash_flights_dict)

    logger.info(f"Found {len(comparison)} flight options with value comparison")
    return comparison


async def compare_award_vs_cash_flights_formatted(
    flight_request: FlightRequest, tool_context: ToolContext
):
    """
    Search for both award and cash flights, then provide value comparison with formatted output.

    This version returns a formatted string with JSON block for frontend parsing.
    Used by the value_comparison_agent.

    Args:
        flight_request: FlightRequest with origin, destination, and outbound_date
        tool_context: ADK tool context for accessing session state (UI filter defaults and custom valuations)

    Returns:
        Formatted string with JSON data block and human-readable analysis
    """
    logger.info(
        f"🔧 COMPARE TOOL CALLED: {flight_request.origin} → {flight_request.destination} on {flight_request.outbound_date}"
    )
    logger.info(
        f"🔧 COMPARE TOOL DEBUG: flight_request details: origin={flight_request.origin}, dest={flight_request.destination}, date={flight_request.outbound_date}, cabin={getattr(flight_request, 'cabin_class', 'not_set')}"
    )

    # Apply UI filter defaults from session state
    apply_ui_filter_defaults(flight_request, tool_context)

    # SMART REUSE: Check for cached search results in session state
    cached_award_results = None
    cached_cash_results = None

    if tool_context and tool_context.state:
        if DEBUG_LOGGING_ENABLED:
            logger.info(
                f"🔍 SESSION STATE DEBUG: tool_context.state type: {type(tool_context.state)}"
            )
            logger.info(
                f"🔍 SESSION STATE DEBUG: tool_context.state dir: {dir(tool_context.state)}"
            )
            # Try to access state as dict-like
            try:
                state_dict = dict(tool_context.state)
                logger.info(
                    f"🔍 SESSION STATE DEBUG: state as dict keys: {list(state_dict.keys())}"
                )
                logger.info(f"🔍 SESSION STATE DEBUG: full state: {state_dict}")
            except Exception as e:
                logger.info(f"🔍 SESSION STATE DEBUG: cannot convert to dict: {e}")

        current_time = datetime.now(timezone.utc)
        cache_window_minutes = 30

        # Check for cached award search
        last_award = tool_context.state.get("last_award_search")
        if last_award:
            if DEBUG_LOGGING_ENABLED:
                logger.info(
                    f"🔍 COMPARE DEBUG: Found last_award_search in state: {last_award.keys() if isinstance(last_award, dict) else type(last_award)}"
                )
            try:
                cache_time = datetime.fromisoformat(
                    last_award["timestamp"].replace("Z", "+00:00")
                )
                time_diff = (current_time - cache_time).total_seconds() / 60

                requested_route = f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
                requested_date = flight_request.outbound_date

                if DEBUG_LOGGING_ENABLED:
                    logger.info(
                        f"🔍 COMPARE DEBUG: Award cache check - requested_route={requested_route}, cached_route={last_award.get('route')}, time_diff={time_diff:.1f}min"
                    )

                if (
                    time_diff <= cache_window_minutes
                    and last_award.get("route") == requested_route
                    and last_award.get("date") == requested_date
                ):
                    cached_award_results = last_award["results"]
                    logger.info(
                        f"🎯 Reusing cached award search results: {len(cached_award_results)} flights, {time_diff:.1f}min old"
                    )
                    if DEBUG_LOGGING_ENABLED:
                        logger.info(
                            f"🔍 Cached award results sample: {cached_award_results[0] if cached_award_results else 'None'}"
                        )
                else:
                    logger.info(
                        f"⏰ Award cache expired or route mismatch: {time_diff:.1f}min old, route={last_award.get('route')} vs {requested_route}"
                    )
            except Exception as e:
                logger.warning(f"Failed to parse award cache timestamp: {e}")
        else:
            if DEBUG_LOGGING_ENABLED:
                logger.info(
                    "🔍 COMPARE DEBUG: No last_award_search found in session state"
                )

        # Check for cached cash search
        last_cash = tool_context.state.get("last_cash_search")
        if last_cash:
            if DEBUG_LOGGING_ENABLED:
                logger.info(
                    f"🔍 COMPARE DEBUG: Found last_cash_search in state: {last_cash.keys() if isinstance(last_cash, dict) else type(last_cash)}"
                )
            try:
                cache_time = datetime.fromisoformat(
                    last_cash["timestamp"].replace("Z", "+00:00")
                )
                time_diff = (current_time - cache_time).total_seconds() / 60

                requested_route = f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
                requested_date = flight_request.outbound_date

                if DEBUG_LOGGING_ENABLED:
                    logger.info(
                        f"🔍 COMPARE DEBUG: Cash cache check - requested_route={requested_route}, cached_route={last_cash.get('route')}, time_diff={time_diff:.1f}min"
                    )

                if (
                    time_diff <= cache_window_minutes
                    and last_cash.get("route") == requested_route
                    and last_cash.get("date") == requested_date
                ):
                    cached_cash_results = last_cash["results"]
                    logger.info(
                        f"🎯 Reusing cached cash search results: {sum(len(flights) for flights in cached_cash_results.values())} flights across {len(cached_cash_results)} cabins, {time_diff:.1f}min old"
                    )
                else:
                    logger.info(
                        f"⏰ Cash cache expired or route mismatch: {time_diff:.1f}min old, route={last_cash.get('route')} vs {requested_route}"
                    )
            except Exception as e:
                logger.warning(f"Failed to parse cash cache timestamp: {e}")
        else:
            if DEBUG_LOGGING_ENABLED:
                logger.info(
                    "🔍 COMPARE DEBUG: No last_cash_search found in session state"
                )

        # Determine what searches we need to perform
        need_award_search = cached_award_results is None
        need_cash_search = cached_cash_results is None

        if DEBUG_LOGGING_ENABLED:
            logger.info(
                f"🔍 COMPARE DEBUG: Cache status - need_award_search={need_award_search}, need_cash_search={need_cash_search}"
            )

        if not need_award_search and not need_cash_search:
            logger.info(
                "🚀 SMART REUSE: Using cached results for both award and cash searches"
            )
            comparison = merge_award_and_cash_flights(
                cached_award_results, cached_cash_results
            )
            logger.info(
                f"📊 Generated comparison from cached data: {len(comparison)} flight options"
            )
        elif not need_award_search and need_cash_search:
            logger.info(
                "🚀 SMART REUSE: Using cached award results, searching for cash flights"
            )
            # Search only cash flights
            cash_flights_dict = await search_cash_flights(flight_request)
            total_cash = sum(len(flights) for flights in cash_flights_dict.values())
            logger.info(
                f"💵 Fetched {total_cash} cash flights across all cabin classes"
            )
            comparison = merge_award_and_cash_flights(
                cached_award_results, cash_flights_dict
            )
            logger.info(
                f"📊 Generated comparison from cached award + new cash: {len(comparison)} flight options"
            )

            # Store cash results in session state
            if tool_context and tool_context.state:
                store_time = datetime.now(timezone.utc).isoformat()
                requested_route = f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
                requested_date = flight_request.outbound_date

                cash_results_serializable = {}
                for cabin, flights in cash_flights_dict.items():
                    cabin_flights = []
                    for flight in flights:
                        if hasattr(flight, "model_dump"):
                            cabin_flights.append(flight.model_dump())
                        else:
                            cabin_flights.append(dict(flight.__dict__))
                    cash_results_serializable[cabin] = cabin_flights

                tool_context.state["last_cash_search"] = {
                    "timestamp": store_time,
                    "route": requested_route,
                    "date": requested_date,
                    "results": cash_results_serializable,
                }
                total_stored = sum(
                    len(flights) for flights in cash_results_serializable.values()
                )
                logger.info(
                    f"💾 Stored {total_stored} cash flights in session state for route {requested_route}"
                )
        elif need_award_search and not need_cash_search:
            logger.info(
                "🚀 SMART REUSE: Using cached cash results, searching for award flights"
            )
            # Search only award flights
            award_flights = search_award_flights(flight_request, tool_context)
            logger.info(
                f"📊 Fetched {len(award_flights)} award flights with trip details"
            )
            comparison = merge_award_and_cash_flights(
                award_flights, cached_cash_results
            )
            logger.info(
                f"📊 Generated comparison from new award + cached cash: {len(comparison)} flight options"
            )

            # Store award results in session state
            if tool_context and tool_context.state:
                store_time = datetime.now(timezone.utc).isoformat()
                requested_route = f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
                requested_date = flight_request.outbound_date

                award_results_dicts = []
                for award in award_flights:
                    if isinstance(award, dict):
                        award_results_dicts.append(award)
                    else:
                        award_dict = (
                            award.model_dump()
                            if hasattr(award, "model_dump")
                            else dict(award.__dict__)
                        )
                        award_results_dicts.append(award_dict)

                tool_context.state["last_award_search"] = {
                    "timestamp": store_time,
                    "route": requested_route,
                    "date": requested_date,
                    "results": award_results_dicts,
                }
                logger.info(
                    f"💾 Stored {len(award_results_dicts)} award flights in session state for route {requested_route}"
                )
        else:
            logger.info(
                "🔄 SMART REUSE: No cached results available, performing both searches in parallel"
            )
            # Perform both searches in parallel for better performance
            import asyncio

            # Run both searches concurrently
            award_task = asyncio.to_thread(
                search_award_flights, flight_request, tool_context
            )
            cash_task = search_cash_flights(flight_request)

            award_flights, cash_flights_dict = await asyncio.gather(
                award_task, cash_task
            )

            logger.info(
                f"📊 Fetched {len(award_flights)} award flights with trip details"
            )
            total_cash = sum(len(flights) for flights in cash_flights_dict.values())
            logger.info(
                f"💵 Fetched {total_cash} cash flights across all cabin classes"
            )

            # Merge and analyze value
            comparison = merge_award_and_cash_flights(award_flights, cash_flights_dict)
            logger.info(
                f"📊 Generated comparison from parallel searches: {len(comparison)} flight options"
            )

            # Store both award and cash results in session state
            if tool_context and tool_context.state:
                store_time = datetime.now(timezone.utc).isoformat()
                requested_route = f"{flight_request.origin.upper()}-{flight_request.destination.upper()}"
                requested_date = flight_request.outbound_date

                # Store award results
                award_results_dicts = []
                for award in award_flights:
                    if isinstance(award, dict):
                        award_results_dicts.append(award)
                    else:
                        # Convert Pydantic object to dict
                        award_dict = (
                            award.model_dump()
                            if hasattr(award, "model_dump")
                            else dict(award.__dict__)
                        )
                        award_results_dicts.append(award_dict)

                tool_context.state["last_award_search"] = {
                    "timestamp": store_time,
                    "route": requested_route,
                    "date": requested_date,
                    "results": award_results_dicts,
                }
                logger.info(
                    f"💾 Stored {len(award_results_dicts)} award flights in session state for route {requested_route}"
                )

                # Store cash results
                cash_results_serializable = {}
                for cabin, flights in cash_flights_dict.items():
                    cabin_flights = []
                    for flight in flights:
                        if hasattr(flight, "model_dump"):
                            cabin_flights.append(flight.model_dump())
                        else:
                            cabin_flights.append(dict(flight.__dict__))
                    cash_results_serializable[cabin] = cabin_flights

                tool_context.state["last_cash_search"] = {
                    "timestamp": store_time,
                    "route": requested_route,
                    "date": requested_date,
                    "results": cash_results_serializable,
                }
                total_stored = sum(
                    len(flights) for flights in cash_results_serializable.values()
                )
                logger.info(
                    f"💾 Stored {total_stored} cash flights across {len(cash_results_serializable)} cabins in session state for route {requested_route}"
                )

    # Get custom valuations from session state (nested in user_profile or at top level)
    personal_valuations = {}
    if tool_context and tool_context.state:
        logger.info(
            f"🔍 SESSION STATE DEBUG: tool_context.state type: {type(tool_context.state)}"
        )

        # Try nested under user_profile first (test environment)
        user_profile_state = tool_context.state.get("user_profile", {})
        if isinstance(user_profile_state, dict):
            personal_valuations = user_profile_state.get("personal_valuations", {})
            logger.info(
                f"📊 Loaded {len(personal_valuations)} custom valuations from session state (nested): {personal_valuations}"
            )
            logger.info(
                f"🔍 user_profile_state keys: {list(user_profile_state.keys())}"
            )
        else:
            logger.info(
                f"user_profile in session state is not a dict: {type(user_profile_state)}"
            )

        # Also try at top level (production environment)
        if not personal_valuations:
            personal_valuations = tool_context.state.get("personal_valuations", {})
            logger.info(
                f"📊 Loaded {len(personal_valuations)} custom valuations from session state (top level): {personal_valuations}"
            )
    else:
        logger.info("🔍 No tool_context.state available")

    # Add effective cost calculation using the same logic as recommendation engine
    from travel_concierge.user_profiles.feasibility import FeasibilityChecker
    from travel_concierge.user_profiles.models import UserPointsProfile, UserPreferences
    from travel_concierge.user_profiles.valuation import ValuationCalculator

    # Initialize with default profile (same as recommendation_tool.py)
    # This ensures we ALWAYS have a user_profile to use FeasibilityChecker
    user_profile = UserPointsProfile(
        user_id="default",
        points_balances={},
        preferences=UserPreferences(),
    )

    # Override with session state data if available
    if tool_context and tool_context.state:
        user_profile_state = tool_context.state.get("user_profile", {})
        if not isinstance(user_profile_state, dict) or not user_profile_state.get(
            "personal_valuations"
        ):
            # Try top level if user_profile is not dict or doesn't have personal_valuations
            user_profile_state = tool_context.state

        if user_profile_state:
            try:
                # Extract data from session state structure (same as recommendation_tool.py)
                available_awards = user_profile_state.get("available_awards")
                session_preferences = user_profile_state.get("preferences")
                # Use the personal_valuations already loaded above (which checks both nested and top-level)
                user_id = user_profile_state.get("user_id", "default")

                # Convert available_awards format
                user_points_balances = {}
                if available_awards:
                    for program, value in available_awards.items():
                        balance = None
                        if isinstance(value, dict) and "points_balance" in value:
                            balance = value["points_balance"]
                        elif isinstance(value, (int, float)):
                            balance = value

                        if balance is not None:
                            # Normalize program name (same logic as recommendation_tool.py)
                            normalized_key = _normalize_session_program_key(program)
                            user_points_balances[normalized_key] = balance

                # Convert preferences
                user_session_preferences = UserPreferences()
                if session_preferences:
                    user_session_preferences = UserPreferences(
                        preferred_cabin=session_preferences.get(
                            "preferred_cabin", "economy"
                        ),
                        max_stops=session_preferences.get("max_stops", 2),
                        min_point_value=session_preferences.get("min_point_value", 1.5),
                        preferred_airlines=session_preferences.get(
                            "preferred_airlines", []
                        ),
                    )

                # Use personal valuations if available (normalize keys like points_balances)
                user_personal_valuations = {}
                if personal_valuations and isinstance(personal_valuations, dict):
                    for program_key, value in personal_valuations.items():
                        if isinstance(value, (int, float)):
                            normalized_key = _normalize_session_program_key(program_key)
                            user_personal_valuations[normalized_key] = float(value)

                # Always recreate profile with session data (even if empty)
                # This ensures consistency with recommendation_tool.py
                user_profile = UserPointsProfile(
                    user_id=user_id,
                    points_balances=user_points_balances,
                    personal_valuations=user_personal_valuations,
                    preferences=user_session_preferences,
                )
                logger.info(
                    f"📊 Created user profile from session state: {len(user_points_balances)} programs, {len(user_personal_valuations)} custom valuations"
                )

            except Exception as e:
                logger.warning(f"Failed to load user profile from session state: {e}")
                import traceback

                logger.debug(f"Session state structure: {tool_context.state}")
                logger.debug(f"Traceback: {traceback.format_exc()}")

    # Always use feasibility checker for accurate effective cost calculation
    # This ensures consistency with recommendation_tool.py
    from travel_concierge.user_profiles.transfers import get_default_graph  # noqa: PLC0415
    feasibility_checker = FeasibilityChecker(transfer_graph=get_default_graph())
    valuation_calculator = ValuationCalculator()

    # Process all comparisons using FeasibilityChecker (consistent with recommendation_tool.py)
    for comp in comparison:
        if comp.get("award"):
            award = comp["award"]
            points = award.get("points", 0)
            taxes = award.get("taxes", 0)
            program_display = award.get("program", "")

            # Map program display names to internal program keys
            program_key = PROGRAM_NAME_MAPPING.get(
                program_display.lower(), program_display.lower().replace(" ", "_")
            )

            try:
                # Check feasibility to get effective cost (considers combination funding)
                # Pass program_key as string (not PointsProgram enum) - same as recommendation.py
                feasibility = feasibility_checker.check_feasibility(
                    user_profile=user_profile,
                    target_program=program_key,
                    points_required=points,
                    taxes_cents=int(taxes * 100),
                )

                if feasibility.best_option:
                    effective_cost_cents = feasibility.best_option.effective_cost_cents
                    comp["effective_cost"] = round(effective_cost_cents / 100, 0)
                    comp["effective_cost_cents"] = effective_cost_cents
                    # Calculate pure valuation (excluding taxes) for consistency with fallback path
                    comp["valuation_used"] = (
                        round((effective_cost_cents - (taxes * 100)) / points, 2)
                        if points > 0
                        else 0
                    )
                    # Log funding option details (source_program shows direct or combination funding)
                    funding_source = feasibility.best_option.source_program
                    logger.info(
                        f"  → Effective cost using feasibility: {points:,} pts → ${comp['effective_cost']} (via {funding_source})"
                    )
                else:
                    # Fallback to simple calculation if no funding option available
                    valuation_cents = valuation_calculator.get_valuation(
                        program_key, user_profile
                    )
                    effective_cost_cents = (points * valuation_cents) + (taxes * 100)
                    comp["effective_cost"] = round(effective_cost_cents / 100, 0)
                    comp["effective_cost_cents"] = effective_cost_cents
                    comp["valuation_used"] = valuation_cents
                    logger.info(
                        f"  → Effective cost fallback: {points:,} × {valuation_cents}¢ + ${taxes} = ${comp['effective_cost']}"
                    )

            except Exception as e:
                logger.warning(
                    f"Failed to calculate effective cost for {program_display}: {e}, using valuation calculator"
                )
                # Fallback to valuation calculator using string key (not enum)
                try:
                    valuation_cents = valuation_calculator.get_valuation(
                        program_key, user_profile
                    )
                except (ValueError, KeyError, AttributeError) as fallback_error:
                    logger.warning(
                        f"Valuation calculator also failed for {program_display}: {fallback_error}, using default 1.5¢"
                    )
                    valuation_cents = 1.5  # Ultimate fallback
                effective_cost_cents = (points * valuation_cents) + (taxes * 100)
                comp["effective_cost"] = round(effective_cost_cents / 100, 0)
                comp["effective_cost_cents"] = effective_cost_cents
                comp["valuation_used"] = valuation_cents
        else:
            comp["effective_cost"] = None
            comp["effective_cost_cents"] = None

    # Sort by effective cost if custom valuations exist, otherwise by CPP
    has_custom_valuations = bool(personal_valuations)
    if has_custom_valuations:
        # Sort by effective cost (lowest first).
        # Use explicit None check — 0-cent cost is valid and must not be treated as infinity.
        comparison.sort(
            key=lambda x: (
                x.get("effective_cost_cents")
                if x.get("effective_cost_cents") is not None
                else float("inf")
            )
        )
        top_3 = [(c.get("airline"), c.get("effective_cost")) for c in comparison[:3]]
        logger.info(f"✅ Sorted by effective cost (custom valuations active): {top_3}")
    else:
        # Sort by CPP (highest first), with USE_POINTS rows ranked above PAY_CASH rows.
        # award_only rows have cpp=0 but recommendation=USE_POINTS — they should appear
        # before cash-only PAY_CASH rows which have no award value at all.
        def _cpp_sort_key(x: dict) -> tuple:
            va = x.get("value_analysis") or {}
            rec = va.get("recommendation", "PAY_CASH")
            cpp = va.get("cpp") or 0
            # Primary: USE_POINTS=0 sorts before PAY_CASH=1
            # Secondary: higher cpp sorts first (negate)
            return (0 if rec == "USE_POINTS" else 1, -cpp)

        comparison.sort(key=_cpp_sort_key)
        logger.info("✅ Sorted by CPP (no custom valuations)")

    # Convert comparison to dict format (show all comparisons)
    comparison_dicts = [
        {
            "route": c.get("route", ""),
            "date": c.get("date", ""),
            "airline": c.get("airline", ""),
            "cabin": c.get("cabin", ""),
            "match_type": c.get("match_type", ""),
            "match_score": c.get("match_score", 0),
            "award": c.get("award", {}),
            "cash": c.get("cash"),
            "value_analysis": c.get("value_analysis", {}),
            "effective_cost": c.get("effective_cost"),
            "effective_cost_cents": c.get("effective_cost_cents"),
            "valuation_used": c.get("valuation_used"),
        }
        for c in comparison
    ]

    json_data = {"comparisons": comparison_dicts}
    json_str = json.dumps(json_data, separators=(",", ":"))

    # Build response with JSON block first (for frontend parsing), then summary
    result = f"```json\n{json_str}\n```\n\n"

    # Add custom valuation indicator if active
    if has_custom_valuations:
        result += "💰 **Custom valuations are being used for effective cost calculations.**\n\n"

    # Text comparison list removed — redundant with the frontend table.
    # The JSON block above is what the frontend parses and renders.
    # Keeping this disabled avoids noisy markdown the LLM echoes back.

    # result += f"Value Comparison Results for {flight_request.origin} to {flight_request.destination}:\n\n"
    #
    # for c in comparison:  # Show all comparisons in markdown
    #     value_analysis = c.get("value_analysis", {}) or {}
    #     award = c.get("award") or {}
    #     cash = c.get("cash")
    #
    #     airline = c.get('airline', 'Unknown')
    #     cabin = c.get('cabin', 'Unknown')
    #     points = award.get('points', 0) if award else 0
    #     taxes = award.get('taxes', 0) if award else 0
    #
    #     result += f"• {airline} {cabin} Class: "
    #
    #     if award:
    #         result += f"{points:,} points + ${taxes:.2f} taxes "
    #
    #     if cash:
    #         cash_price = cash.get('price', 0)
    #         cpp = value_analysis.get('cpp', 0) if value_analysis else 0
    #         recommendation = value_analysis.get('recommendation', 'N/A') if value_analysis else 'N/A'
    #         result += f"vs ${cash_price:,} cash "
    #         result += f"→ {cpp:.2f}¢/point "
    #         result += f"({recommendation})\n"
    #     else:
    #         result += "(no cash option found)\n"

    return result


class ValueComparison(BaseModel):
    """Value comparison between award and cash flights."""

    match_type: str
    match_score: int
    route: str
    date: str
    airline: str
    cabin: str
    award: dict
    cash: dict | None
    value_analysis: dict


class ValueComparisonSelection(BaseModel):
    """A list of flight value comparisons."""

    comparisons: list[ValueComparison]


def search_award_flights_date_range(
    flight_request: FlightDateRangeRequest,
    tool_context: ToolContext = None,
    fetch_trip_details: bool = True,
):
    """Fetch flight details from seats.aero for a date range using user's personal API key.

    Args:
        flight_request: FlightDateRangeRequest with origin, destination, start_date, end_date
        tool_context: ADK tool context for accessing user_id from session state
        fetch_trip_details: If True (default), fetches detailed trip info including flight numbers and times

    Returns:
        List of AwardFlightDetailedInfo objects (if fetch_trip_details=True) or AwardFlightInfo (fallback)
    """
    # Apply UI filter defaults from session state
    apply_ui_filter_defaults(flight_request, tool_context)

    logger.info(
        f"Searching flights: {flight_request.origin} to {flight_request.destination} from {flight_request.start_date} to {flight_request.end_date} (cabin_class={flight_request.cabin_class})"
    )

    # ✅ NEW: Get user's API key from Firebase
    user_id = None
    api_key = None
    if tool_context and tool_context.state:
        user_id = tool_context.state.get("user_id")

    # 🔒 DEFENSE-IN-DEPTH: Enforce subscription tier at code level (even if LLM bypasses prompt)
    # This ensures free-tier users cannot access award search regardless of how the tool is invoked
    if not check_feature_access("award_search", tool_context):
        logger.warning(
            "⚠️ Award search date range blocked: User does not have required subscription tier"
        )
        return [
            {
                "error": "🔒 Award flight search requires a Premium or Pro subscription. Please upgrade to unlock award flight searches and find the best deals using your points and miles.",
                "action": "upgrade_subscription",
            }
        ]

    if user_id:
        api_key = get_user_api_key(user_id, "seats_aero")

    # ✅ NEW: Handle missing API key
    if not api_key:
        # Try environment variable as fallback (for demo/testing)
        api_key = os.getenv("SEATS_AERO_API_KEY")
        if not api_key:
            return [
                {
                    "error": "To search for award flights, please add your Seats.aero API key in Edit Wallet.",
                    "action": "open_edit_wallet",
                }
            ]

    # ✅ MODIFIED: Pass user's API key to SeatsAeroAPI
    try:
        seats_aero_api = SeatsAeroAPI(api_key=api_key)

        data = seats_aero_api.search(
            origin=flight_request.origin,
            destination=flight_request.destination,
            start_date=flight_request.start_date,
            end_date=flight_request.end_date,
        )

        # ✅ NEW: Update last_used timestamp on success
        if user_id and data is not None:
            update_user_api_key_last_used(user_id, "seats_aero")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 or e.response.status_code == 403:
            return [
                {
                    "error": "Your Seats.aero API key appears to be invalid. Please update it in Edit Wallet.",
                    "action": "open_edit_wallet",
                }
            ]
        logger.error(f"Seats.aero API error: {e}")
        return []
    except Exception as e:
        logger.error(f"Error searching award flights: {e}")
        return []

    if data is None:
        return []

    # Check if the top-level 'data' key exists and is a list
    if (
        not isinstance(data, dict)
        or "data" not in data
        or not isinstance(data["data"], list)
    ):
        logger.error(
            "Error: 'data' key not found or is not a list in the JSON response."
        )
        return []

    extracted_results = []
    for item in data["data"]:
        logger.info(item)
        # Extract general route information
        route_info = item.get("Route", {})
        origin = route_info.get("OriginAirport", "N/A")
        destination = route_info.get("DestinationAirport", "N/A")
        flight_date = item.get("Date", "N/A")
        source = item.get("Source", "N/A")

        # Define the cabin classes and their respective keys
        cabin_classes = {
            "Y": "Economy",
            "W": "Premium Economy",
            "J": "Business",
            "F": "First",
        }

        # Iterate through each cabin class to extract its specific details
        for code, name in cabin_classes.items():
            is_available = item.get(f"{code}Available", False)
            remaining_seats = item.get(f"{code}RemainingSeats", 0)
            mileage_cost = item.get(f"{code}MileageCostRaw", 0)
            total_taxes = item.get(f"{code}TotalTaxesRaw", 0)
            taxes_currency = item.get("TaxesCurrency", "N/A")
            airlines = item.get(f"{code}Airlines", "N/A")

            # Only include classes that are available or have a cost/taxes
            if (
                is_available
                or mileage_cost > 0
                or total_taxes > 0
                or remaining_seats > 0
            ):
                # Filter by cabin class if specified
                if (
                    flight_request.cabin_class
                    and name.lower() != flight_request.cabin_class.lower()
                ):
                    continue

                # Filter by direct flights if specified
                is_direct_flight = item.get(f"{code}Direct", False)
                if flight_request.is_direct and not is_direct_flight:
                    continue

                # Filter by max_points if specified
                if (
                    flight_request.max_points > 0
                    and mileage_cost > flight_request.max_points
                ):
                    continue

                # Filter by preferred_airlines if specified
                if (
                    flight_request.preferred_airlines
                    and len(flight_request.preferred_airlines) > 0
                ):
                    airline_list = airlines.split(", ") if airlines != "N/A" else []
                    airline_match = False
                    for airline in airline_list:
                        airline_normalized = normalize_airline_name(airline)
                        preferred_normalized = [
                            normalize_airline_name(a)
                            for a in flight_request.preferred_airlines
                        ]
                        if airline_normalized in preferred_normalized:
                            airline_match = True
                            break
                    if not airline_match:
                        continue

                availability_id = item.get("ID", "")

                if fetch_trip_details and availability_id:
                    # Fetch detailed trip information
                    logger.info(
                        f"🔍 Attempting to fetch trip details for date range: availability_id={availability_id}, cabin={name}"
                    )
                    try:
                        trip_data = seats_aero_api.get_trip(availability_id)
                        logger.info(
                            f"📦 Got trip_data: {bool(trip_data)}, is_dict: {isinstance(trip_data, dict)}"
                        )
                        if trip_data and isinstance(trip_data, dict):
                            trips = trip_data.get("data", [])
                            logger.info(f"📋 Found {len(trips)} trips in response")

                            # Map API cabin names to our internal format
                            # API returns: "economy", "premium", "business", "first"
                            # We use: "economy", "premiumeconomy", "business", "first"
                            cabin_mapping = {
                                "economy": "economy",
                                "premium": "premiumeconomy",  # Map API "premium" → "Premium Economy"
                                "business": "business",
                                "first": "first",
                            }

                            # Find trip that matches the current cabin class
                            target_cabin = name.lower().replace(" ", "")
                            for trip in trips:
                                trip_cabin = trip.get("Cabin", "").lower()
                                # Map API cabin name to our format for comparison
                                mapped_cabin = cabin_mapping.get(trip_cabin, trip_cabin)
                                logger.info(
                                    f"🔍 Checking trip cabin: {trip_cabin} (mapped: {mapped_cabin}) vs target: {target_cabin}"
                                )
                                if mapped_cabin == target_cabin:
                                    flight_numbers = trip.get("FlightNumbers", "")
                                    departs_at = trip.get("DepartsAt", "")
                                    arrives_at = trip.get("ArrivesAt", "")
                                    total_duration = trip.get("TotalDuration", 0)
                                    stops = trip.get("Stops", 0)

                                    # Generate booking URL
                                    booking_url = generate_award_booking_url(
                                        {
                                            "source": source,
                                            "origin": origin,
                                            "destination": destination,
                                            "date": flight_date,
                                            "cabin": name.lower(),
                                        }
                                    )

                                    award_flight_info = AwardFlightDetailedInfo(
                                        source=source,
                                        airline=airlines.split(", ")
                                        if airlines != "N/A"
                                        else [],
                                        mileage_cost=str(mileage_cost),
                                        total_taxes=f"{total_taxes / 100:.2f} {taxes_currency}"
                                        if taxes_currency != "N/A"
                                        else f"{total_taxes / 100:.2f}",
                                        departure=origin,
                                        arrival=destination,
                                        travel_class=name,
                                        date=flight_date,
                                        flight_number=flight_numbers,
                                        departs_at=departs_at,
                                        arrives_at=arrives_at,
                                        total_duration=total_duration,
                                        stops=stops,
                                        remaining_seats=remaining_seats,
                                        availability_id=availability_id,
                                        booking_url=booking_url,
                                    )
                                    extracted_results.append(award_flight_info)
                                    logger.info(
                                        f"✅ Added detailed trip for date range: {flight_numbers} ({name}, cabin={trip_cabin}, date={flight_date})"
                                    )
                                    break  # Found matching cabin, stop searching
                            else:
                                # No matching cabin found, fall through to summary data
                                logger.info(
                                    f"⚠️ No trip found for cabin {target_cabin} in trip {availability_id}, using summary data"
                                )
                                pass  # Fall through to summary data below
                            continue  # Successfully added detailed trip
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch trip details for {availability_id}: {e}"
                        )
                        # Fall back to summary data

                # Summary data (default or fallback)
                award_flight_info = AwardFlightInfo(
                    source=source,
                    airline=airlines.split(", ") if airlines != "N/A" else [],
                    mileage_cost=str(mileage_cost),
                    total_taxes=f"{total_taxes / 100:.2f} {taxes_currency}"
                    if taxes_currency != "N/A"
                    else f"{total_taxes / 100:.2f}",
                    departure=origin,
                    arrival=destination,
                    travel_class=name,
                    date=flight_date,
                )
                extracted_results.append(award_flight_info)

    _store_award_in_state(extracted_results, tool_context, "date range", flight_request)

    return extracted_results


def search_award_flights_date_range_with_count(
    flight_request: FlightDateRangeRequest,
    tool_context: ToolContext | None = None,
    fetch_trip_details: bool = True,
) -> dict:
    """Wrapper around search_award_flights_date_range that returns compact summary metadata.

    The full award flight results are already persisted to session state by
    search_award_flights_date_range via _store_award_in_state. Returning them
    again in the tool response makes the payload unnecessarily large for the
    sub-agent LLM. This wrapper therefore returns only the total count the LLM
    needs to populate AwardFlightSummary.total_found, avoiding the token-scale
    reliability issues that motivated this wrapper.

    Args:
        flight_request: Flight date range search parameters
        tool_context: ADK tool context for session state
        fetch_trip_details: Whether to fetch detailed trip info

    Returns:
        Dict with 'total_count' key
    """
    flights = search_award_flights_date_range(
        flight_request, tool_context, fetch_trip_details
    )
    return {"total_count": len(flights)}
