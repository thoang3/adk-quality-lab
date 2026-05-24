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

"""Hotel search tool using SerpAPI google_hotels engine.

Mirrors the cash_flight_search pattern exactly:
  - search_hotels() calls SerpAPI and persists full results to session state
  - search_hotels_with_count() wraps it and returns only {"total_count": N}
  - HotelSearchSummary is the lean output_schema for hotel_search_agent
"""

import asyncio
import logging
import os
from urllib.parse import quote_plus

from google.adk.tools import ToolContext
from pydantic import BaseModel
from serpapi.google_search import GoogleSearch  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class HotelSearchRequest(BaseModel):
    """Parameters for a SerpAPI google_hotels search."""

    destination: str
    """City or location string, e.g. 'Tokyo, Japan' or 'Paris'."""

    check_in_date: str
    """Check-in date in YYYY-MM-DD format."""

    check_out_date: str
    """Check-out date in YYYY-MM-DD format."""

    adults: int = 2
    """Number of adult guests."""

    currency: str = "USD"
    """ISO 4217 currency code for prices."""

    sort_by: int = 3
    """SerpAPI sort order: 3=lowest price, 8=highest rating, 13=most reviewed."""

    max_price: int = 0
    """Maximum nightly rate in the requested currency (0 = no filter)."""


class HotelSearchSummary(BaseModel):
    """Lean summary returned to planning_agent — zero hotel tokens in context.

    Mirrors CashFlightSummary. The SSE layer captures the full hotel list from
    session state before the agent sees them. hotel_search_agent only needs the
    count + search label to write a short intro.
    """

    total_found: int
    """Total number of hotel properties returned by the search."""

    search_params: str = ""
    """Human-readable label, e.g. 'Tokyo · Jun 1–5 · 2 adults'."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SERP_API_KEY_ENV = "SERP_API_KEY"

# Well-known OTAs — filter out obscure aggregators
_MAJOR_OTAS = {
    "booking.com",
    "expedia",
    "agoda",
    "hotels.com",
    "priceline",
    "kayak",
    "trip.com",
    "orbitz",
    "travelocity",
    "hotwire",
    "cheaptickets",
    "edreams",
    "lastminute.com",
    "marriott",
    "hilton",
    "hyatt",
    "ihg",
}


def _extract_ota_prices(raw: dict) -> list[dict]:
    """Return OTA source names and prices from the initial list response.

    IMPORTANT: In SerpAPI list results, prices[n]['link'] is ALWAYS None.
    OTA booking links are only available via a second detail call using
    property_token.  See fetch_hotel_booking_links() for the detail call.

    This function only extracts source names and price strings — no links.
    The frontend fetches real links lazily via /api/hotel/booking-links.
    """
    raw_prices: list[dict] = raw.get("prices", []) or []
    results = []
    for p in raw_prices:
        source: str = p.get("source", "") or ""
        rate_info = p.get("rate_per_night", {}) or {}
        rate_str: str = rate_info.get("lowest", "") or ""
        rate_num = rate_info.get("extracted_lowest")
        results.append(
            {
                "source": source,
                "rate": rate_str,
                "rate_num": rate_num,
                "link": "",  # always None in list results — fetched via detail call
            }
        )
    # Filter to major OTAs; fall back to all if none match
    major = [
        r for r in results if any(ota in r["source"].lower() for ota in _MAJOR_OTAS)
    ]
    filtered = major if major else results
    # Deduplicate by price, cheapest first.
    # Keep None-price entries distinct per source/rate to avoid collapsing all
    # unknown-price OTAs into a single bucket.
    seen: set[tuple] = set()
    deduped: list[dict] = []

    def _coerce_rate_num(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    def _ota_sort_key(ota: dict) -> tuple[int, float]:
        rate_num = _coerce_rate_num(ota.get("rate_num"))
        if rate_num is not None:
            return (0, rate_num)
        return (1, float("inf"))

    for r in sorted(filtered, key=_ota_sort_key):
        rate_num = _coerce_rate_num(r.get("rate_num"))
        if rate_num is not None:
            key = ("price", rate_num)
        else:
            key = (
                "no_price",
                (r.get("source") or "").strip().lower(),
                (r.get("rate") or "").strip().lower(),
            )
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped[:6]  # cap at 6 OTAs per card


def _get_serp_api_key(tool_context: ToolContext | None) -> str | None:
    """Return SerpAPI key from session state or environment."""
    if tool_context and tool_context.state:
        key = tool_context.state.get("user_serp_api_key")
        if key:
            return key
    return os.getenv(_SERP_API_KEY_ENV)


def _normalize_hotel(raw: dict) -> dict:
    """Extract the fields we care about from a raw SerpAPI property dict."""
    rate = raw.get("rate_per_night") or {}
    total = raw.get("total_rate") or {}
    images = raw.get("images") or []
    thumbnail = (
        images[0].get("original_image", "") if images else raw.get("thumbnail", "")
    )
    name = raw.get("name", "")
    return {
        "name": name,
        "link": raw.get("link", ""),
        "thumbnail": thumbnail,
        "address": raw.get("description", ""),  # SerpAPI puts neighbourhood/desc here
        "check_in_time": raw.get("check_in_time", ""),
        "check_out_time": raw.get("check_out_time", ""),
        "price_per_night": rate.get("lowest", ""),
        "price_per_night_num": rate.get(
            "extracted_lowest"
        ),  # numeric, used for filtering
        "price_total": total.get("lowest", ""),
        "overall_rating": raw.get("overall_rating"),
        "reviews": raw.get("reviews"),
        "amenities": raw.get("amenities", []),
        "hotel_class": raw.get("hotel_class", ""),
        "gps_coordinates": raw.get("gps_coordinates", {}),
        "serpapi_property_id": raw.get("serpapi_property_id", ""),
        "property_token": raw.get("property_token", ""),
        "ota_prices": _extract_ota_prices(raw),
        "google_search_url": f"https://www.google.com/search?q={quote_plus(name + ' hotel')}",
        "google_maps_url": f"https://www.google.com/maps/search/{quote_plus(name)}",
    }


def _store_hotels_in_state(
    hotels: list[dict],
    request: HotelSearchRequest,
    tool_context: ToolContext | None,
) -> None:
    """Persist hotel results to session state for SSE injection & lazy-load."""
    if not tool_context or tool_context.state is None:
        return
    nights = _night_count(request.check_in_date, request.check_out_date)
    tool_context.state["last_hotel_search"] = {
        "results": hotels,
        "destination": request.destination,
        "check_in_date": request.check_in_date,
        "check_out_date": request.check_out_date,
        "adults": request.adults,
        "nights": nights,
    }
    tool_context.state["last_hotel_search_count"] = len(hotels)
    logger.info("💾 Stored %d hotels in session state (last_hotel_search)", len(hotels))


def _night_count(check_in: str, check_out: str) -> int:
    """Return number of nights between two YYYY-MM-DD strings (best-effort)."""
    try:
        from datetime import date

        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
        return max(1, (co - ci).days)
    except Exception:
        return 1


def _coerce_price(value: object) -> float | None:
    """Coerce a price value to float, returning None if it cannot be parsed.

    SerpAPI's ``extracted_lowest`` is documented as numeric but can arrive as
    a numeric-looking string (e.g. ``"150"``).  Using ``or 0`` to guard against
    non-numeric strings would raise ``TypeError`` on comparison, so we coerce
    explicitly and return ``None`` for truly unknown values.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


# SerpAPI's google_hotels returns ~18–20 results per page. We follow
# pagination up to this many pages so the result count varies naturally with
# availability — matching how the flight tools behave — rather than always
# showing a fixed ceiling.
#
# TODO(personalization): There are effectively "infinite" hotels available, so
# future work should drive SerpAPI filter params from the user's profile before
# fetching — preferred hotel chains/brands (brands param), star class, budget,
# min rating, amenities, party size, and free-cancellation preference — rather
# than paginating a generic list.
_HOTEL_MAX_PAGES = 3


def _fetch_page(params: dict) -> dict:
    """Synchronous SerpAPI call — runs in a thread pool via asyncio.to_thread."""
    return GoogleSearch(params).get_dict()


async def search_hotels(
    hotel_request: HotelSearchRequest,
    tool_context: ToolContext | None = None,
) -> dict:
    """Search for hotels using SerpAPI google_hotels engine.

    Fetches up to ``_HOTEL_MAX_PAGES`` pages in sequence (following
    ``next_page_token``). Each SerpAPI page returns ~18–20 properties, so the
    total varies naturally with availability rather than being capped at a fixed
    number. Full results are persisted to session state for SSE injection.

    Args:
        hotel_request: Hotel search parameters.
        tool_context: ADK tool context for session state and API key lookup.

    Returns:
        ``{"hotels": [...]}`` on success, or ``{"error": "<message>"}`` on failure.
    """
    api_key = _get_serp_api_key(tool_context)
    if not api_key:
        msg = "SerpAPI key not configured. Set the SERP_API_KEY environment variable."
        logger.error(msg)
        _store_hotels_in_state([], hotel_request, tool_context)
        return {"error": msg}

    base_params: dict = {
        "engine": "google_hotels",
        "q": hotel_request.destination,
        "check_in_date": hotel_request.check_in_date,
        "check_out_date": hotel_request.check_out_date,
        "adults": hotel_request.adults,
        "currency": hotel_request.currency,
        "sort_by": hotel_request.sort_by,
        "hl": "en",
        "gl": "us",
        "api_key": api_key,
    }
    if hotel_request.max_price > 0:
        base_params["max_price"] = hotel_request.max_price

    raw_properties: list[dict] = []
    params = dict(base_params)

    for page_num in range(1, _HOTEL_MAX_PAGES + 1):
        try:
            results = await asyncio.to_thread(_fetch_page, params)
        except Exception as exc:  # pragma: no cover — network errors
            logger.exception(
                "SerpAPI google_hotels call failed (page %d): %s", page_num, exc
            )
            if page_num == 1:
                _store_hotels_in_state([], hotel_request, tool_context)
                return {"error": str(exc)}
            break  # Keep whatever we collected on earlier pages

        page_props: list[dict] = results.get("properties", [])
        raw_properties.extend(page_props)
        logger.info(
            "🏨 page %d: %d properties (total so far: %d)",
            page_num,
            len(page_props),
            len(raw_properties),
        )

        # Stop if there's no next page
        next_page_token = (results.get("serpapi_pagination", {}) or {}).get(
            "next_page_token"
        )
        if not next_page_token:
            break
        params = dict(base_params)
        params["next_page_token"] = next_page_token

    if not raw_properties:
        logger.warning(
            "SerpAPI returned no properties for '%s' (%s–%s)",
            hotel_request.destination,
            hotel_request.check_in_date,
            hotel_request.check_out_date,
        )
        _store_hotels_in_state([], hotel_request, tool_context)
        return {"hotels": []}

    # Deduplicate by serpapi_property_id (pages can overlap for some destinations)
    seen_ids: set[str] = set()
    unique_raw: list[dict] = []
    for prop in raw_properties:
        pid = prop.get("serpapi_property_id") or prop.get("name", "")
        if pid not in seen_ids:
            seen_ids.add(pid)
            unique_raw.append(prop)

    hotels = [_normalize_hotel(h) for h in unique_raw]

    # Apply client-side numeric price filter as a safety net after server-side
    # max_price param (SerpAPI may not enforce it perfectly for all properties).
    # Uses the numeric extracted_lowest field — no string parsing.
    if hotel_request.max_price > 0:
        hotels = [
            h
            for h in hotels
            if (lambda p: p is None or p <= hotel_request.max_price)(
                _coerce_price(h.get("price_per_night_num"))
            )
        ]

    _store_hotels_in_state(hotels, hotel_request, tool_context)
    logger.info(
        "✅ hotel search '%s' returned %d properties",
        hotel_request.destination,
        len(hotels),
    )
    return {"hotels": hotels}


async def search_hotels_with_count(
    hotel_request: HotelSearchRequest,
    tool_context: ToolContext | None = None,
) -> dict:
    """Wrapper around search_hotels that returns compact summary metadata.

    The full hotel results are already persisted to session state by
    search_hotels via _store_hotels_in_state. Returning them again in the
    tool response makes the payload unnecessarily large for the sub-agent LLM.
    This wrapper therefore returns only the total count the LLM needs to write
    a short intro, avoiding token-scale reliability issues.

    Args:
        hotel_request: Hotel search parameters.
        tool_context: ADK tool context for session state.

    Returns:
        ``{"total_count": N}`` on success, or ``{"error": "<message>"}`` on
        failure — preserving the underlying error so the sub-agent can surface
        a useful message instead of silently reporting zero hotels.
    """
    result = await search_hotels(hotel_request, tool_context)
    if "error" in result and "hotels" not in result:
        return result
    hotels = result.get("hotels", [])
    return {"total_count": len(hotels)}


def get_hotel_context(
    name: str | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    hotel_class: int | None = None,
    tool_context: ToolContext | None = None,
) -> list[dict]:
    """Retrieve hotel search results from session state, with optional filters.

    Call this when the user asks a follow-up question about hotels from the
    current search (e.g. "tell me more about the Park Hyatt", "any 5-star
    options?", "what's under $200/night?"). Use filter parameters to load only
    the relevant subset and keep token cost proportional to the question.

    Do NOT call this on the initial search response — use the total_found and
    search_params from the hotel_search_agent's summary instead.

    Hotels are identified by name fragment — never by row position, since the
    frontend grid is not guaranteed to be in a stable order.

    Args:
        name: Case-insensitive substring match on hotel name
            (e.g. "Park Hyatt", "Marriott").
        max_price: Filter to hotels with nightly rate ≤ this value (numeric).
        min_rating: Filter to hotels with overall_rating ≥ this value
            (e.g. 4.5).
        hotel_class: Filter by star class — exact match (e.g. 4 or 5).
        tool_context: ADK tool context for session state access.

    Returns:
        Matching hotel dicts from the most recent search, or an empty list if
        no hotel search has been performed yet.
    """
    if not tool_context or not tool_context.state:
        logger.warning("get_hotel_context: no tool_context or state available")
        return []

    search_data = tool_context.state.get("last_hotel_search", {})
    hotels: list[dict] = (
        search_data.get("results", []) if isinstance(search_data, dict) else []
    )
    logger.info("get_hotel_context: loaded %d hotels from session state", len(hotels))

    # Apply filters — each is optional, all combine with AND logic
    needle = name.lower().strip() if name else ""
    if needle:
        hotels = [h for h in hotels if needle in h.get("name", "").lower()]
        logger.debug(
            "get_hotel_context: after name filter (%r): %d hotels", name, len(hotels)
        )

    if max_price is not None:
        hotels = [
            h
            for h in hotels
            if (lambda p: p is None or p <= max_price)(
                _coerce_price(h.get("price_per_night_num"))
            )
        ]
        logger.debug(
            "get_hotel_context: after max_price filter (%s): %d hotels",
            max_price,
            len(hotels),
        )

    if min_rating is not None:
        hotels = [h for h in hotels if (h.get("overall_rating") or 0) >= min_rating]
        logger.debug(
            "get_hotel_context: after min_rating filter (%s): %d hotels",
            min_rating,
            len(hotels),
        )

    if hotel_class is not None:
        hotels = [
            h
            for h in hotels
            if _parse_hotel_class(h.get("hotel_class", "")) == hotel_class
        ]
        logger.debug(
            "get_hotel_context: after hotel_class filter (%d): %d hotels",
            hotel_class,
            len(hotels),
        )

    logger.info("get_hotel_context: returning %d hotels", len(hotels))
    return hotels


def _parse_hotel_class(value: str | int | float | None) -> int:
    """Parse a hotel class value to an integer (e.g. '4-star hotel' → 4)."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        # SerpAPI returns e.g. '4-star hotel' or just '4'
        import re

        m = re.search(r"(\d+)", value)
        if m:
            return int(m.group(1))
    return 0
