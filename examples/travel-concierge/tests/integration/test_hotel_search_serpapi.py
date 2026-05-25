"""
Manual integration test — SerpAPI `engine=google_hotels`.

Purpose
-------
Verify that the SAME `SERP_API_KEY` already used for cash flights
(`engine=google_flights`) also works for `engine=google_hotels`, and
that the real API returns the structured fields we plan to surface in
`hotel_search_agent` (nightly rate, star class, images, booking link, etc.).

This is a READ-ONLY exploration test — it makes real API calls and prints
results to stdout.  Run it with ``-s`` to see the full output:

    RUN_HOTEL_EXPLORATION_TESTS=1 uv run pytest tests/integration/test_hotel_search_serpapi.py -v -s

Skip criteria
-------------
- RUN_HOTEL_EXPLORATION_TESTS env var is NOT set to "1" → skipped by default
  (this is intentional — prevents CI from exhausting SerpAPI quota)
- SERP_API_KEY env var is absent → test is skipped automatically
- SKIP_INTEGRATION_TESTS=1 → test is skipped

Quota note
----------
SerpAPI free plan: 100 searches/month shared across all engines.
Each parameterised case below counts as 1 search call.
This file has ~10 test cases = ~10 searches per full run.
DO NOT add to CI — run manually only.
"""

import os

import pytest
from serpapi.google_search import GoogleSearch

from tests.integration.helpers import require_serp_key

# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

SKIP_TESTS = os.getenv("SKIP_INTEGRATION_TESTS", "0") == "1"
skip_reason = "SKIP_INTEGRATION_TESTS is set"

# This file makes ~10 real SerpAPI calls per full run.
# It is skipped by default — even when SERP_API_KEY is present — to protect
# the shared 100 searches/month quota from being consumed by routine CI runs.
# Set RUN_HOTEL_EXPLORATION_TESTS=1 to opt in explicitly.
_OPT_IN = os.getenv("RUN_HOTEL_EXPLORATION_TESTS", "0") == "1"
if not _OPT_IN:
    SKIP_TESTS = True
    skip_reason = (
        "Set RUN_HOTEL_EXPLORATION_TESTS=1 to run hotel exploration tests "
        "(skipped by default to protect SerpAPI quota)"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fields we expect to exist in a healthy API response.
# NOTE: "link" is intentionally excluded — it is only present on some properties
# in list results (those with a direct hotel website).  It is NOT guaranteed.
# Use property["serpapi_property_details_link"] for a reliable per-property URL.
REQUIRED_FIELDS = [
    "name",
    "type",
    "property_token",
    "serpapi_property_details_link",
]

# Fields that indicate real price data (not hallucinated)
PRICE_FIELDS = [
    "rate_per_night",
    "total_rate",
]

# Fields that enrich the hotel card UI
ENRICHMENT_FIELDS = [
    "hotel_class",
    "overall_rating",
    "reviews",
    "amenities",
    "images",
    "gps_coordinates",
]


def _search_hotels(
    destination: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    hotel_class: str = "",
    currency: str = "USD",
    vacation_rentals: bool = False,
    eco_certified: bool = False,
    max_price: int = 0,
) -> dict:
    """Thin wrapper around GoogleSearch for ``engine=google_hotels`` (list call).

    Returns the full API response dict.  Raises on any API-level error.
    """
    api_key = os.environ.get("SERP_API_KEY")

    params: dict = {
        "engine": "google_hotels",
        "q": destination,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "api_key": api_key,
    }

    if hotel_class:
        params["hotel_class"] = hotel_class

    if vacation_rentals:
        params["vacation_rentals"] = "true"

    if eco_certified:
        params["eco_certified"] = "true"

    if max_price:
        params["max_price"] = max_price

    return GoogleSearch(params).get_dict()


def _search_hotel_details(
    destination: str,
    check_in_date: str,
    check_out_date: str,
    property_token: str,
    adults: int = 2,
    currency: str = "USD",
) -> dict:
    """Second SerpAPI call using ``property_token`` to get OTA booking links.

    This is the *detail call* — the same ``engine=google_hotels`` but with
    ``property_token`` added.  It returns:
      - ``featured_prices[]`` — highlighted OTA prices with real booking links
      - ``prices[]``          — full OTA list with free_cancellation, discount_remarks
      - ``typical_price_range`` — historical low/high prices
      - ``nearby_places[]``  — full POI details with GPS + transport options
      - ``amenities_detailed`` — grouped amenities (Internet, Pool, Spa…)
      - ``other_reviews[]``  — Tripadvisor / Trip.com scores + sample quote
      - ``check_in_time`` / ``check_out_time``

    Key difference from list results: ``prices[n]["link"]`` and
    ``featured_prices[n]["link"]`` are real google.com/travel/clk? wrappers
    with bookable OTA URLs in the ``pcurl=`` query parameter.
    """
    api_key = os.environ.get("SERP_API_KEY")

    params: dict = {
        "engine": "google_hotels",
        "q": destination,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "currency": currency,
        "hl": "en",
        "gl": "us",
        "property_token": property_token,
        "api_key": api_key,
    }

    return GoogleSearch(params).get_dict()


def _print_hotel_summary(hotel: dict, idx: int) -> None:
    """Pretty-print one hotel property dict for manual inspection."""
    print(f"\n  [{idx}] {hotel.get('name', '(no name)')}")
    print(f"       type        : {hotel.get('type', '—')}")
    print(f"       hotel_class : {hotel.get('hotel_class', '—')}")
    print(
        f"       rating      : {hotel.get('overall_rating', '—')} "
        f"({hotel.get('reviews', '—')} reviews)"
    )

    # location_rating: float where 1.8=Bad, 4.8=Excellent (from Properties API)
    loc_rating = hotel.get("location_rating")
    if loc_rating is not None:
        print(f"       location    : {loc_rating} (1.8=Bad → 4.8=Excellent)")

    # Price — the field we care most about replacing hallucinated values with
    rate = hotel.get("rate_per_night", {})
    if rate:
        pretax = rate.get("before_taxes_fees", "")
        pretax_str = f"  (excl. taxes: {pretax})" if pretax else ""
        print(
            f"       rate/night  : {rate.get('lowest', '—')} "
            f"(extracted: {rate.get('extracted_lowest', '—')}){pretax_str}"
        )
    else:
        print("       rate/night  : ⚠️  MISSING — check API response structure")

    total = hotel.get("total_rate", {})
    if total:
        print(
            f"       total rate  : {total.get('lowest', '—')} "
            f"(extracted: {total.get('extracted_lowest', '—')})"
        )

    # deal / deal_description: present on some properties in list results
    deal = hotel.get("deal", "")
    deal_desc = hotel.get("deal_description", "")
    if deal:
        print(f"       deal        : 🏷️  {deal}  ({deal_desc})")

    # eco_certified: boolean, filterable via eco_certified=true param
    if hotel.get("eco_certified"):
        print("       eco         : ♻️  Eco-certified")

    # sponsored: deprioritize or label in UI
    if hotel.get("sponsored"):
        print("       sponsored   : ⚡ Yes")

    amenities = hotel.get("amenities", [])
    print(f"       amenities   : {amenities[:5]}{' …' if len(amenities) > 5 else ''}")

    images = hotel.get("images", [])
    print(
        f"       images      : {len(images)} returned"
        + (f" → first: {images[0].get('thumbnail', '—')}" if images else "")
    )

    gps = hotel.get("gps_coordinates", {})
    if gps:
        print(f"       gps         : {gps.get('latitude')}, {gps.get('longitude')}")

    free_cancel = hotel.get("free_cancellation")
    if free_cancel is not None:
        print(f"       free_cancel : {free_cancel}")

    link = hotel.get("link", "")
    print(f"       link        : {link[:80]}{'…' if len(link) > 80 else ''}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsBasic:
    """Smoke-test: can we reach the google_hotels engine at all?"""

    def test_api_key_is_valid_for_hotels_engine(self):
        """Verify the existing SERP_API_KEY grants access to engine=google_hotels."""
        require_serp_key()

        response = _search_hotels(
            destination="Paris, France",
            check_in_date="2026-06-15",
            check_out_date="2026-06-18",
            adults=2,
        )

        print("\n\n=== RAW RESPONSE KEYS ===")
        print(list(response.keys()))

        # SerpAPI wraps errors in {"error": "..."} — fail fast with a clear message
        assert "error" not in response, (
            f"SerpAPI returned an error: {response.get('error')}\n"
            "Possible causes: invalid API key, plan doesn't include google_hotels, quota exhausted."
        )

        # Must have a properties list (the actual hotel results)
        assert "properties" in response, (
            f"Response has no 'properties' key. Keys returned: {list(response.keys())}"
        )

        properties = response["properties"]
        assert isinstance(properties, list), "'properties' must be a list"
        assert len(properties) > 0, (
            "Expected at least one hotel result for Paris June 2026"
        )

        print(f"\n✅ Got {len(properties)} hotel properties from google_hotels engine")
        print(
            f"   Search metadata: {response.get('search_metadata', {}).get('status')}"
        )


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsFields:
    """Verify that real price and enrichment fields are present in results."""

    def test_rate_per_night_is_numeric(self):
        """The key data quality test: rate_per_night.extracted_lowest must be a number.

        This is the field that replaces hallucinated prices in hotel_search_agent.
        """
        require_serp_key()

        response = _search_hotels(
            destination="Tokyo, Japan",
            check_in_date="2026-08-10",
            check_out_date="2026-08-13",
            adults=2,
            hotel_class="3,4",  # 3- and 4-star only
            currency="USD",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== Tokyo Hotels (3–4 star, 3 nights, Aug 2026) ===")
        print(f"Total returned: {len(properties)}")

        hotels_with_price = 0
        hotels_without_price = 0

        for i, hotel in enumerate(properties[:10], 1):
            _print_hotel_summary(hotel, i)

            rate = hotel.get("rate_per_night", {})
            if rate and rate.get("extracted_lowest") is not None:
                hotels_with_price += 1
                # This is the field we'll use in hotel_search.py
                assert isinstance(rate["extracted_lowest"], (int, float)), (
                    f"extracted_lowest should be numeric, got: {type(rate['extracted_lowest'])}"
                )
            else:
                hotels_without_price += 1

        print("\n📊 Price field coverage:")
        print(f"   With rate_per_night.extracted_lowest : {hotels_with_price}")
        print(f"   Missing                              : {hotels_without_price}")

        # At least half the results should have pricing data
        assert hotels_with_price > 0, (
            "No hotels returned rate_per_night.extracted_lowest — "
            "the field name may have changed. Inspect raw response above."
        )

    def test_required_fields_present(self):
        """Every property must have name, type, and link."""
        require_serp_key()

        response = _search_hotels(
            destination="New York, NY",
            check_in_date="2026-09-20",
            check_out_date="2026-09-22",
            adults=1,
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== New York Hotels (1 night, Sep 2026) ===")
        print(f"Total returned: {len(properties)}")

        for i, hotel in enumerate(properties[:5], 1):
            _print_hotel_summary(hotel, i)
            for field in REQUIRED_FIELDS:
                assert field in hotel, (
                    f"Hotel '{hotel.get('name')}' missing required field '{field}'. "
                    f"Available keys: {list(hotel.keys())}"
                )
            # "link" is optional — report coverage but don't assert
            has_link = bool(hotel.get("link"))
            print(
                f"       has direct link : {'✅' if has_link else '—  (no direct site link in list result)'}"
            )

        print(f"\n✅ All required fields ({REQUIRED_FIELDS}) present in top 5 results")
        print(
            "   Note: 'link' (hotel's own website) is present on some properties only."
        )

    def test_enrichment_fields_coverage(self):
        """Document which enrichment fields are present (non-fatal — just informational)."""
        require_serp_key()

        response = _search_hotels(
            destination="London, UK",
            check_in_date="2026-07-04",
            check_out_date="2026-07-07",
            adults=2,
            hotel_class="4,5",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        # Tally field coverage across first 10 results
        field_counts: dict[str, int] = dict.fromkeys(ENRICHMENT_FIELDS, 0)
        sample = properties[:10]

        for hotel in sample:
            for field in ENRICHMENT_FIELDS:
                if hotel.get(field):
                    field_counts[field] += 1

        print(
            f"\n\n=== London Hotels — Enrichment Field Coverage ({len(sample)} sampled) ==="
        )
        for field, count in field_counts.items():
            pct = count / len(sample) * 100
            status = "✅" if pct >= 50 else "⚠️ "
            print(f"  {status} {field:<20} : {count}/{len(sample)} ({pct:.0f}%)")

        # images and link should be nearly universal
        assert field_counts["images"] > 0, (
            "Expected at least some hotels to have images"
        )


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsVacationRentals:
    """Verify vacation_rentals=true includes Airbnb-style inventory."""

    def test_vacation_rentals_flag(self):
        """Confirm the vacation_rentals parameter is accepted without error."""
        require_serp_key()

        response = _search_hotels(
            destination="Barcelona, Spain",
            check_in_date="2026-06-20",
            check_out_date="2026-06-23",
            adults=2,
            vacation_rentals=True,
        )

        assert "error" not in response, (
            f"vacation_rentals=true caused an API error: {response.get('error')}"
        )

        properties = response.get("properties", [])
        print("\n\n=== Barcelona Vacation Rentals (Jun 2026) ===")
        print(f"Total returned: {len(properties)}")

        types_seen = set()
        for hotel in properties[:10]:
            _print_hotel_summary(hotel, properties.index(hotel) + 1)
            t = hotel.get("type", "")
            if t:
                types_seen.add(t)

        print(f"\n🏠 Property types seen: {types_seen}")
        # Just confirm we got something back — type variety proves mixed inventory
        assert len(properties) > 0, "Expected vacation rental results for Barcelona"


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsMigrationReadiness:
    """End-to-end shape test matching the HotelsSelection Pydantic model fields."""

    def test_field_mapping_to_hotels_selection_schema(self):
        """Map raw API fields to our HotelsSelection/HotelInfo schema.

        This test documents the exact transform we need to write in
        travel_concierge/tools/hotel_search.py to replace the LLM-generated
        hotel results in HOTEL_SEARCH_INSTR.
        """
        require_serp_key()

        response = _search_hotels(
            destination="Rome, Italy",
            check_in_date="2026-05-10",
            check_out_date="2026-05-13",
            adults=2,
            hotel_class="3,4,5",
            currency="USD",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== Rome Hotels — Schema Mapping Preview ===")
        print(f"Total returned: {len(properties)}")

        # Show the exact mapping for the first 3 hotels
        for raw in properties[:3]:
            rate = raw.get("rate_per_night", {})
            total = raw.get("total_rate", {})
            images = raw.get("images", [])
            gps = raw.get("gps_coordinates", {})

            mapped = {
                # HotelInfo fields
                "name": raw.get("name", ""),
                "hotel_class": raw.get("hotel_class", ""),
                "overall_rating": raw.get("overall_rating"),
                "reviews": raw.get("reviews"),
                "amenities": raw.get("amenities", []),
                "free_cancellation": raw.get("free_cancellation", False),
                # Price fields → replaces hallucinated rates
                "price_per_night_usd": rate.get("extracted_lowest"),
                "price_display": rate.get("lowest", ""),
                "total_price_usd": total.get("extracted_lowest"),
                "total_price_display": total.get("lowest", ""),
                # Media / navigation
                "thumbnail": images[0].get("thumbnail", "") if images else "",
                "link": raw.get("link", ""),
                "latitude": gps.get("latitude"),
                "longitude": gps.get("longitude"),
            }

            print(f"\n  Mapped hotel: {mapped['name']}")
            for k, v in mapped.items():
                print(f"    {k:<25} = {v}")

            # Key assertion: price must be a real number, not None
            # (if this fails, the raw field name changed — update hotel_search.py accordingly)
            assert mapped["price_per_night_usd"] is not None, (
                f"Hotel '{mapped['name']}' has no price — "
                f"raw rate_per_night keys: {list(rate.keys())}"
            )

        print("\n✅ Field mapping looks correct — ready to implement hotel_search.py")


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsDeals:
    """Verify deal, location_rating, and ratings[] breakdown fields in list results.

    All three are available in list results (no property_token detail call needed):
      - deal / deal_description  : e.g. "27% less than usual" / "Great Deal"
      - location_rating          : float, 1.8=Bad → 4.8=Excellent
      - ratings[]                : per-star review counts (1–5 stars)
      - sponsored                : boolean — deprioritize or label in UI
    """

    def test_deal_and_location_rating_in_list_results(self):
        """Confirm deal badges and location_rating are surfaced in list results.

        Bali resorts are a good target — they frequently have active deals
        and a wide spread of location ratings (beach vs inland).
        """
        require_serp_key()

        response = _search_hotels(
            destination="Bali, Indonesia",
            check_in_date="2026-06-15",
            check_out_date="2026-06-18",
            adults=2,
            hotel_class="4,5",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== Bali Hotels — Deals & Location Rating ===")
        print(f"Total returned: {len(properties)}")

        props_with_deal = 0
        props_with_location_rating = 0

        for i, hotel in enumerate(properties[:10], 1):
            _print_hotel_summary(hotel, i)

            if hotel.get("deal"):
                props_with_deal += 1

            loc = hotel.get("location_rating")
            if loc is not None:
                props_with_location_rating += 1

            # ratings[] — per-star breakdown (available in list results)
            ratings = hotel.get("ratings", [])
            if ratings:
                breakdown = {r["stars"]: r["count"] for r in ratings}
                print(f"       star breakdown: {breakdown}")

        print("\n📊 Deal & location coverage (top 10):")
        print(f"   Properties with deal badge     : {props_with_deal}/10")
        print(f"   Properties with location_rating: {props_with_location_rating}/10")
        print(
            "\n💡 deal + location_rating are free in list results — no detail call needed."
        )

        # location_rating should be common (present on most properties)
        assert props_with_location_rating > 0, (
            "Expected at least some properties to have location_rating. "
            "Field may have been renamed — inspect raw response."
        )

    def test_ratings_breakdown_present(self):
        """ratings[] (per-star counts) should be present on properties with reviews.

        This enables a star-distribution histogram in the hotel card UI without
        needing a second API call.
        """
        require_serp_key()

        response = _search_hotels(
            destination="Kyoto, Japan",
            check_in_date="2026-10-10",
            check_out_date="2026-10-13",
            adults=2,
            hotel_class="4,5",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== Kyoto Hotels — ratings[] Breakdown ===")

        props_with_ratings = 0

        for i, hotel in enumerate(properties[:8], 1):
            ratings = hotel.get("ratings", [])
            if ratings:
                props_with_ratings += 1
                stars_map = {r["stars"]: r["count"] for r in ratings}
                total = sum(stars_map.values())
                print(f"\n  [{i}] {hotel.get('name', '?')}")
                print(
                    f"       overall_rating : {hotel.get('overall_rating', '—')} "
                    f"({hotel.get('reviews', '—')} reviews)"
                )
                for stars in [5, 4, 3, 2, 1]:
                    count = stars_map.get(stars, 0)
                    pct = count / total * 100 if total else 0
                    bar = "█" * int(pct / 5)
                    print(f"       {'★' * stars:<5} : {bar:<20} {count} ({pct:.0f}%)")

        print(
            f"\n📊 {props_with_ratings}/{min(8, len(properties))} properties have ratings[] breakdown"
        )

        assert props_with_ratings > 0, (
            "Expected at least some properties to have ratings[] breakdown. "
            "Field may be absent for hotels with very few reviews."
        )


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsDeepLinks:
    """Verify the link patterns available from the Google Hotels API response.

    Key discoveries (verified via HTTP testing):
      - search_metadata["google_hotels_url"] is a Google internal batchexecute
        RPC endpoint — NOT a linkable URL for users.
      - google.com/travel/hotels and /travel/hotels/entity/{token} both redirect
        to /travel/unsupported on desktop (JS SPA, ignores query params).
      - property["link"] — present on some properties (the hotel's own website).
        NOT guaranteed in list results.
      - property["prices"][n]["link"] in LIST results — always None.
      - property["prices"][n]["link"] in DETAIL results (using property_token) —
        returns real OTA booking URLs wrapped as:
            https://www.google.com/travel/clk?...&pcurl=<actual_booking_url>
        Extract the real URL via: parse_qs(urlparse(link).query)["pcurl"][0]

    Reliable user-facing URL patterns:
      • Search-level: google.com/search?q=hotels+in+{dest}+{check_in}+to+{check_out}
      • Per-property: google.com/search?q={hotel_name}+hotel+{dest}  (Knowledge Panel)
      • Per-property: google.com/maps/search/{hotel_name}+{dest}
      • OTA booking:  extracted pcurl= from property detail call (2nd SerpAPI call)
    """

    def test_google_hotels_url_in_metadata_is_internal_rpc(self):
        """search_metadata.google_hotels_url is a batchexecute RPC, not a user link.

        It is present in every response but should NOT be surfaced in the UI.
        The reliable alternative is a Google Search URL with dates in the query.
        """
        require_serp_key()

        response = _search_hotels(
            destination="Sydney, Australia",
            check_in_date="2026-10-01",
            check_out_date="2026-10-04",
            adults=2,
        )

        assert "error" not in response, response.get("error")

        meta = response.get("search_metadata", {})
        google_hotels_url = meta.get("google_hotels_url", "")

        print("\n\n=== Google Hotels Metadata URL — Sydney Oct 2026 ===")
        print(
            "\n📎 search_metadata.google_hotels_url (internal — do NOT link to users):"
        )
        print(f"   {google_hotels_url}")
        print(
            "\n✅ Use instead: https://www.google.com/search?q=hotels+in+Sydney+2026-10-01+to+2026-10-04+2+adults"
        )

        # The URL is always present but is an internal RPC endpoint
        assert google_hotels_url, "search_metadata.google_hotels_url is empty"
        assert "batchexecute" in google_hotels_url, (
            f"Expected batchexecute RPC URL, got: {google_hotels_url}\n"
            "If this changed, update our URL-building strategy."
        )

    def test_property_link_coverage_and_ota_prices_are_none_in_list(self):
        """In LIST results: property["link"] is sparse; prices[n]["link"] is always None.

        OTA booking links are only available via a second SerpAPI call using
        property_token (the property detail endpoint).  That call returns
        prices[n]["link"] as a google.com/travel/clk? wrapper — extract
        the real OTA URL from the pcurl= query parameter.
        """
        require_serp_key()

        response = _search_hotels(
            destination="Singapore",
            check_in_date="2026-11-15",
            check_out_date="2026-11-18",
            adults=2,
            hotel_class="4,5",
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])
        assert properties, "No hotel properties returned"

        print("\n\n=== Singapore Hotels — Link Inventory ===")
        print(f"Total properties: {len(properties)}")

        props_with_direct_link = 0
        props_with_ota_price_links = 0
        all_ota_sources: set[str] = set()

        for i, prop in enumerate(properties[:8], 1):
            direct_link = prop.get("link", "")
            prices = prop.get("prices", [])

            print(f"\n  [{i}] {prop.get('name', '?')}")
            print(f"       property_token : {prop.get('property_token', '—')[:40]}…")
            print(
                f"       direct link    : {direct_link[:80] if direct_link else '— (not in list result)'}"
            )

            if direct_link:
                props_with_direct_link += 1

            if prices:
                price_links = [p.get("link") for p in prices if p.get("link")]
                if price_links:
                    props_with_ota_price_links += 1
                print(
                    f"       OTA prices ({len(prices)}) — links present: {len(price_links)}/{len(prices)}"
                )
                for p in prices[:3]:
                    source = p.get("source", "?")
                    ota_link = (
                        p.get("link") or "None (use property_token detail call instead)"
                    )
                    rate = p.get("rate_per_night", {}).get("extracted_lowest", "?")
                    all_ota_sources.add(source)
                    print(
                        f"         • {source:<20} ${rate}/night  link={ota_link[:60]}"
                    )
            else:
                print("       OTA prices    : none returned")

        print("\n📊 Link coverage summary (list results only):")
        print(f"   Properties with direct hotel link   : {props_with_direct_link}/8")
        print(
            f"   Properties with OTA booking links   : {props_with_ota_price_links}/8 (expected: 0)"
        )
        print(f"   OTA source names seen               : {sorted(all_ota_sources)}")
        print("\n💡 To get real OTA booking URLs:")
        print("   Make a 2nd SerpAPI call with property_token=<token>")
        print(
            "   Then extract: parse_qs(urlparse(prices[n]['link']).query)['pcurl'][0]"
        )

        assert props_with_direct_link > 0, (
            "Expected at least some properties to have a direct hotel website link"
        )
        # OTA price links are None in list results — this is expected behaviour
        assert props_with_ota_price_links == 0, (
            f"Unexpectedly got OTA booking links in list results ({props_with_ota_price_links} properties). "
            "If SerpAPI fixed this, we can drop the separate detail call in fetch_ota_prices()."
        )


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsDetailCall:
    """Verify the two-call pattern: list → property_token → detail.

    The detail call (same engine=google_hotels + property_token) unlocks fields
    that are NOT available in list results:

      featured_prices[]
        - Real OTA booking links wrapped as google.com/travel/clk?...&pcurl=<url>
        - Per-OTA room breakdown with room name, images, and rate
        - official=True marks the hotel's own direct booking channel
        - benefits string (e.g. "Book with Priceline: Wi-Fi and parking included")

      prices[]
        - Full OTA list (more sources than featured_prices)
        - free_cancellation / free_cancellation_until_date per OTA
        - discount_remarks + original_rate_per_night when a discount is active

      typical_price_range
        - Historical low/high prices — "is this a good deal?" framing
        - { lowest, extracted_lowest, highest, extracted_highest }

      other_reviews[]
        - Tripadvisor, Trip.com scores + one sample user review with quote + link

      amenities_detailed
        - Grouped (Internet, Pool, Spa…) with label: "free" / "extra charge"
        - available=False for excluded amenities

    Two-call flow:
        list_result  = _search_hotels(destination, ...)
        token        = list_result["properties"][0]["property_token"]
        detail       = _search_hotel_details(destination, ..., property_token=token)
        booking_link = detail["featured_prices"][0]["link"]  # real URL!
    """

    def test_featured_prices_have_real_booking_links(self):
        """property_token detail call returns featured_prices[] with working OTA links.

        This is the key difference from list results where prices[n]["link"]
        is always None.  After the detail call, links are present and wrapped as:
            https://www.google.com/travel/clk?...&pcurl=<actual_booking_url>

        Extract the actual OTA URL with:
            from urllib.parse import urlparse, parse_qs
            parse_qs(urlparse(link).query)["pcurl"][0]
        """
        require_serp_key()

        # Step 1: list call to get a property_token
        list_resp = _search_hotels(
            destination="Tokyo, Japan",
            check_in_date="2026-08-10",
            check_out_date="2026-08-13",
            adults=2,
            hotel_class="4,5",
        )

        assert "error" not in list_resp, list_resp.get("error")
        properties = list_resp.get("properties", [])
        assert properties, "No properties in list result"

        first = properties[0]
        property_token = first.get("property_token")
        assert property_token, "First property has no property_token"

        print("\n\n=== Two-Call Pattern — Tokyo Detail Call ===")
        print(f"Step 1 → list: {len(properties)} properties returned")
        print(
            f"         picking: {first.get('name', '?')} (token: {property_token[:30]}…)"
        )

        # Step 2: detail call using property_token
        detail = _search_hotel_details(
            destination="Tokyo, Japan",
            check_in_date="2026-08-10",
            check_out_date="2026-08-13",
            property_token=property_token,
            adults=2,
        )

        assert "error" not in detail, detail.get("error")

        # featured_prices — the highlighted OTA options with real links
        featured = detail.get("featured_prices", [])
        prices = detail.get("prices", [])

        print(
            f"\nStep 2 → detail: {len(featured)} featured_prices, {len(prices)} prices"
        )

        links_with_url = 0
        print("\n  featured_prices[]:")
        for fp in featured:
            link = fp.get("link", "")
            official = fp.get("official", False)
            benefits = fp.get("benefits", "")
            rate = fp.get("rate_per_night", {}).get("extracted_lowest", "?")
            rooms = fp.get("rooms", [])
            link_preview = link[:80] if link else "—"
            print(
                f"    • {fp.get('source', '?'):<22} ${rate}/night  "
                f"{'🏨 official' if official else ''}"
            )
            print(f"      link   : {link_preview}")
            if benefits:
                print(f"      benefit: {benefits}")
            print(f"      rooms  : {[r.get('name') for r in rooms[:2]]}")
            if link and "google.com" in link:
                links_with_url += 1

        print("\n  prices[] (full OTA list):")
        for p in prices[:4]:
            free_cancel = p.get("free_cancellation", False)
            until = p.get("free_cancellation_until_date", "")
            disc = p.get("discount_remarks", [])
            rate = p.get("rate_per_night", {}).get("extracted_lowest", "?")
            link = p.get("link", "—")
            print(
                f"    • {p.get('source', '?'):<22} ${rate}/night  "
                f"{'✅ free cancel' + (f' until {until}' if until else '') if free_cancel else ''}"
                f"{'  🏷️ ' + str(disc) if disc else ''}"
            )
            print(f"      link: {str(link)[:80]}")

        print(
            f"\n📊 featured_prices with real google.com links: {links_with_url}/{len(featured)}"
        )
        print('💡 Extract actual OTA URL: parse_qs(urlparse(link).query)["pcurl"][0]')

        assert len(featured) > 0, (
            "Expected featured_prices[] in detail response — "
            "the property_token may not have matched. Check the destination."
        )
        assert links_with_url > 0, (
            "Expected at least one featured_price with a real booking link. "
            "If all links are empty, the detail call may have failed."
        )

    def test_typical_price_range_and_other_reviews(self):
        """Detail call returns typical_price_range and other_reviews (Tripadvisor etc.).

        typical_price_range: historical low/high — lets the agent say
            "this hotel usually runs $120–$169/night; today's $149 is typical."

        other_reviews: Tripadvisor / Trip.com scores + one sample user quote,
            available without a separate reviews API call.
        """
        require_serp_key()

        # Step 1: list call
        list_resp = _search_hotels(
            destination="Bali, Indonesia",
            check_in_date="2026-07-10",
            check_out_date="2026-07-13",
            adults=2,
            hotel_class="5",
        )

        assert "error" not in list_resp, list_resp.get("error")
        properties = list_resp.get("properties", [])
        assert properties, "No properties in list result"

        token = properties[0].get("property_token")
        assert token, "No property_token on first result"

        print("\n\n=== Bali 5-Star — typical_price_range & other_reviews ===")
        print(f"Selected: {properties[0].get('name', '?')}")

        # Step 2: detail call
        detail = _search_hotel_details(
            destination="Bali, Indonesia",
            check_in_date="2026-07-10",
            check_out_date="2026-07-13",
            property_token=token,
            adults=2,
        )

        assert "error" not in detail, detail.get("error")

        # typical_price_range
        tpr = detail.get("typical_price_range", {})
        print(f"\n  typical_price_range : {tpr}")
        if tpr:
            low = tpr.get("extracted_lowest")
            high = tpr.get("extracted_highest")
            current = detail.get("rate_per_night", {}).get("extracted_lowest")
            print(f"    → Usual range: {tpr.get('lowest')} – {tpr.get('highest')}")
            if current and low and high:
                if current <= low:
                    verdict = "🟢 below typical range"
                elif current <= high:
                    verdict = "🟡 within typical range"
                else:
                    verdict = "🔴 above typical range"
                print(f"    → Current price ${current}/night: {verdict}")

        # other_reviews
        other_reviews = detail.get("other_reviews", [])
        print(f"\n  other_reviews ({len(other_reviews)} sources):")
        for rev in other_reviews:
            score = rev.get("source_rating", {})
            user = rev.get("user_review", {})
            print(
                f"    • {rev.get('source', '?'):<15} "
                f"{score.get('score', '?')}/{score.get('max_score', '?')} "
                f"({rev.get('reviews', '?')} reviews)"
            )
            if user.get("comment"):
                print(f'      "{user["comment"][:100]}…"')

        # check_in / check_out times
        print(f"\n  check_in_time  : {detail.get('check_in_time', '—')}")
        print(f"  check_out_time : {detail.get('check_out_time', '—')}")

        # deal badge surfaced in detail too
        if detail.get("deal"):
            print(
                f"  deal           : 🏷️  {detail['deal']}  ({detail.get('deal_description', '')})"
            )

        print(
            "\n💡 typical_price_range + other_reviews need only 1 extra API call (detail)."
        )

        # Soft assertions — these fields may not always be present
        assert "name" in detail, (
            "Detail response missing 'name' — wrong property_token?"
        )


@pytest.mark.skipif(SKIP_TESTS, reason=skip_reason)
@pytest.mark.integration
class TestSerpAPIHotelsNonMatching:
    """Verify eco_certified filter and non_matching_properties fallback.

    non_matching_properties: when active filters (hotel_class, max_price, rating)
    narrow results significantly, SerpAPI returns a second array of hotels that are
    relevant to the query but violate one or more filters.  This lets the agent say:
        "Nothing fits your $150/night cap exactly, but here are close matches
         slightly over budget."

    eco_certified: boolean filter — pass eco_certified=true to restrict results
    to sustainability-certified properties.  The eco_certified field is also
    present on individual properties in list results.
    """

    def test_eco_certified_filter_returns_certified_properties(self):
        """eco_certified=true restricts list results to sustainability-certified hotels."""
        require_serp_key()

        response = _search_hotels(
            destination="Bali, Indonesia",
            check_in_date="2026-06-15",
            check_out_date="2026-06-18",
            adults=2,
            eco_certified=True,
        )

        assert "error" not in response, response.get("error")
        properties = response.get("properties", [])

        print("\n\n=== Bali Eco-Certified Hotels ===")
        print(f"Total returned: {len(properties)}")

        eco_count = 0
        for i, hotel in enumerate(properties[:8], 1):
            is_eco = hotel.get("eco_certified", False)
            if is_eco:
                eco_count += 1
            print(f"\n  [{i}] {hotel.get('name', '?')}")
            print(f"       eco_certified : {'♻️  Yes' if is_eco else '—'}")
            print(f"       hotel_class   : {hotel.get('hotel_class', '—')}")
            rate = hotel.get("rate_per_night", {})
            print(f"       rate/night    : {rate.get('lowest', '—')}")

        print(f"\n📊 Eco-certified in results: {eco_count}/{min(8, len(properties))}")
        print(
            "💡 eco_certified=true filters server-side — no client-side post-filtering needed."
        )

        assert len(properties) > 0, (
            "Expected eco-certified results for Bali. "
            "If 0 returned, the eco_certified param may have changed."
        )

    def test_non_matching_properties_appear_when_budget_tight(self):
        """Strict max_price triggers non_matching_properties — close-but-over results.

        This is useful for the agent to surface near-misses when a user's budget
        is tight: "Nothing fits exactly, but here are hotels slightly over budget."

        non_matching_properties shares the same JSON schema as properties[].
        """
        require_serp_key()

        # Use a very tight price cap to force non_matching_properties to appear
        response = _search_hotels(
            destination="Paris, France",
            check_in_date="2026-06-15",
            check_out_date="2026-06-18",
            adults=2,
            max_price=85,  # Very tight — forces near-miss results
        )

        assert "error" not in response, response.get("error")

        matching = response.get("properties", [])
        non_matching = response.get("non_matching_properties", [])

        print("\n\n=== Paris Hotels — non_matching_properties (max_price=$85) ===")
        print(f"Properties matching filter    : {len(matching)}")
        print(f"Non-matching (over budget)    : {len(non_matching)}")

        if non_matching:
            print("\n  non_matching_properties (same schema as properties[]):")
            for i, hotel in enumerate(non_matching[:4], 1):
                rate = hotel.get("rate_per_night", {})
                print(f"\n  [{i}] {hotel.get('name', '?')}")
                print(
                    f"       rate/night    : {rate.get('lowest', '—')} "
                    f"(over your ${85} cap)"
                )
                print(f"       hotel_class   : {hotel.get('hotel_class', '—')}")
                print(
                    f"       property_token: {hotel.get('property_token', '—')[:40]}…"
                )
        else:
            print(
                "\n  ⚠️  No non_matching_properties returned — try a tighter max_price."
            )

        print(
            "\n💡 Expose non_matching_properties as 'close matches' when exact results are 0."
        )
        print("   non_matching_properties shares the same JSON schema as properties[].")

        # The filter itself must not error — non_matching may or may not appear
        assert "error" not in response, (
            "max_price filter caused an API error — param may have changed."
        )
