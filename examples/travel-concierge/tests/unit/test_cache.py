import asyncio
import time
from unittest.mock import MagicMock

import pytest

from travel_concierge.tools.cache import (
    Cache,
    canonicalize_search_params,
    compute_cache_key,
)
from travel_concierge.tools.search import FlightRequest


def test_canonicalize_search_params_basic():
    request = FlightRequest(origin="SFO", destination="NRT", outbound_date="2026-03-15")
    result = canonicalize_search_params(request, "cash")
    expected = {
        "search_type": "cash",
        "destination": "NRT",  # Specific airport code preserved
        "origin": "SFO",
        "outbound_date": "2026-03-15",
        "cabin_class": None,
        "direct_filter": False,  # ✅ Binary: False for multi-stop (no max_stops specified)
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_with_city_names():
    request = FlightRequest(
        origin="San Francisco", destination="Tokyo", outbound_date="2026-03-15"
    )
    result = canonicalize_search_params(request, "cash")
    expected = {
        "search_type": "cash",
        "destination": "NRT",  # City name 'Tokyo' maps to primary airport NRT
        "origin": "SFO",  # City name 'San Francisco' maps to SFO
        "outbound_date": "2026-03-15",
        "cabin_class": None,
        "direct_filter": False,  # ✅ Binary: False for multi-stop (no max_stops specified)
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_with_optional_fields():
    # Mock request with additional fields
    request = MagicMock()
    request.origin = "SFO"
    request.destination = "NRT"
    request.outbound_date = "2026-03-15"
    request.cabin_class = "business"
    request.travelers = 2
    request.preferences = {"direct_only": True}

    result = canonicalize_search_params(request, "cash")
    expected = {
        "search_type": "cash",
        "destination": "NRT",  # Specific airport code preserved
        "origin": "SFO",
        "outbound_date": "2026-03-15",
        "cabin_class": "business",
        "direct_filter": False,  # ✅ Binary: False for multi-stop (no max_stops specified)
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_removes_empty():
    request = MagicMock()
    request.origin = "SFO"
    request.destination = "NRT"
    request.outbound_date = "2026-03-15"
    request.cabin_class = ""  # Empty
    request.preferences = {}  # Empty dict

    result = canonicalize_search_params(request, "cash")
    expected = {
        "search_type": "cash",
        "destination": "NRT",  # Specific airport code preserved
        "origin": "SFO",
        "outbound_date": "2026-03-15",
        "cabin_class": None,
        "direct_filter": False,  # ✅ Binary: False for multi-stop (no max_stops specified)
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_award_binary_direct():
    """Test that award searches collapse max_stops to binary direct_filter."""
    # Test max_stops=0 (nonstop only) → direct_filter=True
    request_nonstop = FlightRequest(
        origin="SEA", destination="HAN", outbound_date="2026-06-15", max_stops=0
    )
    result_nonstop = canonicalize_search_params(request_nonstop, "award")
    assert result_nonstop["direct_filter"] is True

    # Test max_stops=1 → direct_filter=False (shares cache with max_stops=2, None)
    request_one_stop = FlightRequest(
        origin="SEA", destination="HAN", outbound_date="2026-06-15", max_stops=1
    )
    result_one_stop = canonicalize_search_params(request_one_stop, "award")
    assert result_one_stop["direct_filter"] is False

    # Test max_stops=2 → direct_filter=False (SAME as max_stops=1!)
    request_two_stops = FlightRequest(
        origin="SEA", destination="HAN", outbound_date="2026-06-15", max_stops=2
    )
    result_two_stops = canonicalize_search_params(request_two_stops, "award")
    assert result_two_stops["direct_filter"] is False

    # Verify cache key sharing
    key_one = compute_cache_key(result_one_stop)
    key_two = compute_cache_key(result_two_stops)
    assert key_one == key_two, "max_stops=1 and max_stops=2 should share cache key!"


def test_canonicalize_search_params_cash_binary_direct():
    """Test that cash searches collapse max_stops to binary direct_filter for SUPERSET caching."""
    # Test max_stops=0 (nonstop only) → direct_filter=True
    request_nonstop = FlightRequest(
        origin="JFK", destination="LAX", outbound_date="2026-05-20", max_stops=0
    )
    result_nonstop = canonicalize_search_params(request_nonstop, "cash")
    assert result_nonstop["direct_filter"] is True, (
        "max_stops=0 should set direct_filter=True"
    )

    # Test max_stops=1 → direct_filter=False (shares cache with max_stops=2, None)
    request_one_stop = FlightRequest(
        origin="JFK", destination="LAX", outbound_date="2026-05-20", max_stops=1
    )
    result_one_stop = canonicalize_search_params(request_one_stop, "cash")
    assert result_one_stop["direct_filter"] is False, (
        "max_stops=1 should set direct_filter=False"
    )

    # Test max_stops=2 → direct_filter=False (SAME as max_stops=1!)
    request_two_stops = FlightRequest(
        origin="JFK", destination="LAX", outbound_date="2026-05-20", max_stops=2
    )
    result_two_stops = canonicalize_search_params(request_two_stops, "cash")
    assert result_two_stops["direct_filter"] is False, (
        "max_stops=2 should set direct_filter=False"
    )

    # Test max_stops=None → direct_filter=False (SAME as max_stops=1 and 2!)
    request_any_stops = FlightRequest(
        origin="JFK", destination="LAX", outbound_date="2026-05-20", max_stops=None
    )
    result_any_stops = canonicalize_search_params(request_any_stops, "cash")
    assert result_any_stops["direct_filter"] is False, (
        "max_stops=None should set direct_filter=False"
    )

    # Verify cache key sharing for all multi-stop searches
    key_one = compute_cache_key(result_one_stop)
    key_two = compute_cache_key(result_two_stops)
    key_any = compute_cache_key(result_any_stops)
    assert key_one == key_two == key_any, (
        "max_stops=1, 2, None should share cache key (SUPERSET caching)!"
    )

    # Verify direct search gets separate cache
    key_nonstop = compute_cache_key(result_nonstop)
    assert key_nonstop != key_one, (
        "Direct (max_stops=0) must have separate cache from multi-stop"
    )


def test_canonicalize_search_params_cash_is_direct_flag():
    """Test that is_direct=True sets direct_filter=True for cash searches."""
    request_direct = FlightRequest(
        origin="ORD", destination="DEN", outbound_date="2026-07-10", is_direct=True
    )
    result_direct = canonicalize_search_params(request_direct, "cash")
    assert result_direct["direct_filter"] is True, (
        "is_direct=True should set direct_filter=True"
    )

    # Verify it shares cache with max_stops=0
    request_max_stops_zero = FlightRequest(
        origin="ORD", destination="DEN", outbound_date="2026-07-10", max_stops=0
    )
    result_max_stops_zero = canonicalize_search_params(request_max_stops_zero, "cash")

    key_direct = compute_cache_key(result_direct)
    key_max_stops_zero = compute_cache_key(result_max_stops_zero)
    assert key_direct == key_max_stops_zero, (
        "is_direct=True and max_stops=0 should share cache"
    )


def test_compute_cache_key_basic():
    canonical_params = {
        "origin": "SFO",
        "destination": "NRT",
        "outbound_date": "2026-03-15",
        "schema_version": "v3",
    }
    result = compute_cache_key(canonical_params)  # ✅ One arg
    # Verify it's a valid sha256 hash
    assert len(result) == 64
    assert result.isalnum()


def test_compute_cache_key_deterministic():
    params1 = {"a": 1, "b": 2, "schema_version": "v3"}
    params2 = {"b": 2, "a": 1, "schema_version": "v3"}  # Same content, different order
    key1 = compute_cache_key(params1)
    key2 = compute_cache_key(params2)
    assert key1 == key2


def test_compute_cache_key_different_params():
    params1 = {"origin": "SFO", "schema_version": "v3"}
    params2 = {"origin": "LAX", "schema_version": "v3"}
    key1 = compute_cache_key(params1)
    key2 = compute_cache_key(params2)
    assert key1 != key2


def test_cache_set_and_get():
    cache = Cache(ttl_seconds=60)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_ttl_expiry():
    cache = Cache(ttl_seconds=1)
    cache.set("key1", "value1")
    time.sleep(1.1)
    cache.evict_expired()
    assert cache.get("key1") is None


def test_cache_max_entries_lru():
    cache = Cache(max_entries=2)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")  # Should evict key1
    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    assert cache.get("key3") == "value3"


def test_cache_clear():
    cache = Cache()
    cache.set("key1", "value1")
    cache.clear()
    assert cache.get("key1") is None


@pytest.mark.asyncio
async def test_get_or_compute_hit():
    cache = Cache()
    cache.set("key1", "cached_value")

    async def compute_func():
        return "new_value"

    result = await cache.get_or_compute("key1", compute_func)
    assert result == "cached_value"


@pytest.mark.asyncio
async def test_get_or_compute_miss():
    cache = Cache()

    async def compute_func():
        return "computed_value"

    result = await cache.get_or_compute("key1", compute_func)
    assert result == "computed_value"
    assert cache.get("key1") == "computed_value"


@pytest.mark.asyncio
async def test_get_or_compute_stampede_protection():
    cache = Cache()
    call_count = 0

    async def slow_compute():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return f"value{call_count}"

    # Simulate concurrent calls
    tasks = [cache.get_or_compute("key1", slow_compute) for _ in range(5)]
    results = await asyncio.gather(*tasks)
    assert all(r == "value1" for r in results)  # Only computed once
    assert call_count == 1


def test_specific_airports_get_separate_cache_entries():
    """
    Verify that specific airport codes (NRT, HND) produce different cache keys.
    This ensures we don't serve NRT results for HND searches.
    """
    # Specific airport codes should be preserved
    request_nrt = FlightRequest(
        origin="JFK", destination="NRT", outbound_date="2026-03-15"
    )
    request_hnd = FlightRequest(
        origin="JFK", destination="HND", outbound_date="2026-03-15"
    )

    canonical_nrt = canonicalize_search_params(request_nrt, "cash")
    canonical_hnd = canonicalize_search_params(request_hnd, "cash")

    # They should have different destinations
    assert canonical_nrt["destination"] == "NRT"
    assert canonical_hnd["destination"] == "HND"

    # And therefore different cache keys
    key_nrt = compute_cache_key(canonical_nrt)  # ✅ No profile_fingerprint arg
    key_hnd = compute_cache_key(canonical_hnd)  # ✅ No profile_fingerprint arg
    assert key_nrt != key_hnd, "NRT and HND must produce different cache keys"


def test_city_name_maps_to_primary_airport():
    """
    Verify that city names map to primary airports, allowing them to share cache.
    """
    # City name should map to primary airport
    request_city = FlightRequest(
        origin="JFK", destination="Tokyo", outbound_date="2026-03-15"
    )
    request_airport = FlightRequest(
        origin="JFK", destination="NRT", outbound_date="2026-03-15"
    )

    canonical_city = canonicalize_search_params(request_city, "cash")
    canonical_airport = canonicalize_search_params(request_airport, "cash")

    # "Tokyo" should canonicalize to "NRT" (primary airport)
    assert canonical_city["destination"] == "NRT"
    assert canonical_airport["destination"] == "NRT"

    # They should produce the same cache key
    key_city = compute_cache_key(canonical_city)  # ✅ No profile_fingerprint arg
    key_airport = compute_cache_key(canonical_airport)  # ✅ No profile_fingerprint arg
    assert key_city == key_airport, "'Tokyo' and 'NRT' should share the same cache"


def test_expanded_city_mapping():
    """
    Verify that the expanded city mapping (100+ cities) works correctly.
    Tests major cities from different regions to ensure comprehensive coverage.
    """
    test_cases = [
        # Asia
        ("Bangkok", "BKK"),
        ("Singapore", "SIN"),
        ("Hong Kong", "HKG"),
        ("Seoul", "ICN"),
        ("Dubai", "DXB"),
        # Europe
        ("Amsterdam", "AMS"),
        ("Barcelona", "BCN"),
        ("Istanbul", "IST"),
        ("Athens", "ATH"),
        ("Stockholm", "ARN"),
        # South America
        ("Sao Paulo", "GRU"),
        ("Buenos Aires", "EZE"),
        ("Lima", "LIM"),
        # Oceania
        ("Sydney", "SYD"),
        ("Melbourne", "MEL"),
        ("Auckland", "AKL"),
        # Africa
        ("Johannesburg", "JNB"),
        ("Cairo", "CAI"),
        # Case insensitivity
        ("BANGKOK", "BKK"),
        ("singapore", "SIN"),
        ("HoNg KoNg", "HKG"),
    ]

    for city_name, expected_code in test_cases:
        request = FlightRequest(
            origin="SFO", destination=city_name, outbound_date="2026-03-15"
        )
        result = canonicalize_search_params(request, "cash")
        assert result["destination"] == expected_code, (
            f"City '{city_name}' should map to '{expected_code}', got '{result['destination']}'"
        )


def test_unmapped_city_fallback():
    """
    Verify that unmapped cities fall back to uppercased input.
    This preserves airport codes that aren't in the city mapping.
    """
    # Unknown city/airport - should uppercase but not change
    request = FlightRequest(origin="SFO", destination="XYZ", outbound_date="2026-03-15")
    result = canonicalize_search_params(request, "cash")
    assert result["destination"] == "XYZ", (
        "Unmapped airport codes should be preserved as uppercase"
    )

    # Edge case: What if user types a city we don't recognize?
    # It will be uppercased, which may not be ideal but is deterministic
    request2 = FlightRequest(
        origin="SFO", destination="Timbuktu", outbound_date="2026-03-15"
    )
    result2 = canonicalize_search_params(request2, "cash")
    assert result2["destination"] == "TIMBUKTU", (
        "Unmapped city names are uppercased (not ideal, but deterministic)"
    )


def test_canonicalize_search_params_award_basic():
    """Test award search canonicalization with basic parameters."""
    request = FlightRequest(origin="SFO", destination="NRT", outbound_date="2026-03-15")
    result = canonicalize_search_params(request, "award")
    expected = {
        "search_type": "award",
        "destination": "NRT",
        "origin": "SFO",
        "outbound_date": "2026-03-15",
        "cabin_class": None,
        "direct_filter": False,  # ✅ New: replaces max_stops for award
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_award_with_city_names():
    """Test award search canonicalization with city names."""
    request = FlightRequest(
        origin="San Francisco", destination="Tokyo", outbound_date="2026-03-15"
    )
    result = canonicalize_search_params(request, "award")
    expected = {
        "search_type": "award",
        "destination": "NRT",  # City name 'Tokyo' maps to primary airport NRT
        "origin": "SFO",  # City name 'San Francisco' maps to SFO
        "outbound_date": "2026-03-15",
        "cabin_class": None,
        "direct_filter": False,  # ✅ New: replaces max_stops for award
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_canonicalize_search_params_award_with_optional_fields():
    """Test award search canonicalization with optional fields."""
    # Mock request with additional fields
    request = MagicMock()
    request.origin = "SFO"
    request.destination = "NRT"
    request.outbound_date = "2026-03-15"
    request.cabin_class = "business"
    request.max_points = 50000
    request.travelers = 2
    request.preferences = {"direct_only": True}

    result = canonicalize_search_params(request, "award")
    expected = {
        "search_type": "award",
        "destination": "NRT",
        "origin": "SFO",
        "outbound_date": "2026-03-15",
        "cabin_class": "business",
        "direct_filter": False,  # ✅ New: replaces max_stops for award
        "schema_version": "v3",  # ✅ Updated
    }
    assert result == expected


def test_compute_cache_key_award_vs_cash():
    """Test that award and cash searches produce different cache keys."""
    params = {
        "origin": "SFO",
        "destination": "NRT",
        "outbound_date": "2026-03-15",
        "schema_version": "v3",
    }

    # Cash search
    cash_params = params.copy()
    cash_params["search_type"] = "cash"
    cash_key = compute_cache_key(cash_params)  # ✅ No profile_fingerprint arg

    # Award search
    award_params = params.copy()
    award_params["search_type"] = "award"
    award_key = compute_cache_key(award_params)  # ✅ No profile_fingerprint arg

    assert cash_key != award_key, (
        "Cash and award searches must produce different cache keys"
    )


def test_award_search_city_name_maps_to_primary_airport():
    """Test that award searches with city names map to primary airports."""
    # City name should map to primary airport
    request_city = FlightRequest(
        origin="JFK", destination="Tokyo", outbound_date="2026-03-15"
    )
    request_airport = FlightRequest(
        origin="JFK", destination="NRT", outbound_date="2026-03-15"
    )

    canonical_city = canonicalize_search_params(request_city, "award")
    canonical_airport = canonicalize_search_params(request_airport, "award")

    # "Tokyo" should canonicalize to "NRT" (primary airport)
    assert canonical_city["destination"] == "NRT"
    assert canonical_airport["destination"] == "NRT"
    assert canonical_city["search_type"] == "award"
    assert canonical_airport["search_type"] == "award"

    # They should produce the same cache key
    key_city = compute_cache_key(canonical_city)  # ✅ No profile_fingerprint arg
    key_airport = compute_cache_key(canonical_airport)  # ✅ No profile_fingerprint arg
    assert key_city == key_airport, (
        "'Tokyo' and 'NRT' should share the same award cache"
    )


def test_award_search_expanded_city_mapping():
    """Test award search city mapping for major cities."""
    test_cases = [
        ("Bangkok", "BKK"),
        ("Singapore", "SIN"),
        ("Hong Kong", "HKG"),
        ("Amsterdam", "AMS"),
        ("Sydney", "SYD"),
    ]

    for city_name, expected_code in test_cases:
        request = FlightRequest(
            origin="SFO", destination=city_name, outbound_date="2026-03-15"
        )
        result = canonicalize_search_params(request, "award")
        assert result["destination"] == expected_code, (
            f"Award search: City '{city_name}' should map to '{expected_code}', got '{result['destination']}'"
        )
        assert result["search_type"] == "award"
