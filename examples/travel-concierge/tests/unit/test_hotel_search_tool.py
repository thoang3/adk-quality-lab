"""Unit tests for adk_quality_lab_wiring.tools.hotel_search.

No network calls — SerpAPI is mocked at the module level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adk_quality_lab_wiring.tools.hotel_search import (
    HotelSearchRequest,
    HotelSearchSummary,
    _coerce_price,
    _extract_ota_prices,
    _night_count,
    _normalize_hotel,
    _parse_hotel_class,
    get_hotel_context,
    search_hotels,
    search_hotels_with_count,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RAW_HOTEL = {
    "name": "Grand Palace Hotel",
    "link": "https://example.com/grand-palace",
    "description": "Luxury hotel in central Tokyo",
    "check_in_time": "3:00 PM",
    "check_out_time": "11:00 AM",
    "rate_per_night": {"lowest": "$200"},
    "total_rate": {"lowest": "$800"},
    "overall_rating": 4.5,
    "reviews": 2341,
    "amenities": ["Pool", "WiFi", "Gym"],
    "hotel_class": "4-star hotel",
    "images": [{"original_image": "https://example.com/img.jpg"}],
    "gps_coordinates": {"latitude": 35.6895, "longitude": 139.6917},
    "serpapi_property_id": "PROP123",
}

HOTEL_REQUEST = HotelSearchRequest(
    destination="Tokyo, Japan",
    check_in_date="2025-06-01",
    check_out_date="2025-06-05",
    adults=2,
)


def _make_tool_context(state: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


# ---------------------------------------------------------------------------
# _normalize_hotel
# ---------------------------------------------------------------------------


def test_normalize_hotel_extracts_expected_fields():
    result = _normalize_hotel(RAW_HOTEL)
    assert result["name"] == "Grand Palace Hotel"
    assert result["link"] == "https://example.com/grand-palace"
    assert result["thumbnail"] == "https://example.com/img.jpg"
    assert result["check_in_time"] == "3:00 PM"
    assert result["check_out_time"] == "11:00 AM"
    assert result["price_per_night"] == "$200"
    assert result["price_total"] == "$800"
    assert result["overall_rating"] == 4.5
    assert result["reviews"] == 2341
    assert "Pool" in result["amenities"]
    assert result["serpapi_property_id"] == "PROP123"


def test_normalize_hotel_missing_images_falls_back_to_thumbnail():
    raw = {**RAW_HOTEL, "images": [], "thumbnail": "https://fallback.png"}
    result = _normalize_hotel(raw)
    assert result["thumbnail"] == "https://fallback.png"


def test_extract_ota_prices_keeps_distinct_none_price_sources():
    raw = {
        "prices": [
            {
                "source": "Booking.com",
                "rate_per_night": {"lowest": "$200", "extracted_lowest": None},
            },
            {
                "source": "Expedia",
                "rate_per_night": {"lowest": "$210", "extracted_lowest": None},
            },
            {
                "source": "Booking.com",
                "rate_per_night": {"lowest": "$200", "extracted_lowest": None},
            },
        ]
    }

    result = _extract_ota_prices(raw)
    assert [r["source"] for r in result] == ["Booking.com", "Expedia"]


def test_extract_ota_prices_preserves_price_and_none_dedup_behavior():
    raw = {
        "prices": [
            {
                "source": "Booking.com",
                "rate_per_night": {"lowest": "$199", "extracted_lowest": 199},
            },
            {
                "source": "Hotels.com",
                "rate_per_night": {"lowest": "$199", "extracted_lowest": "199"},
            },
            {
                "source": "Expedia",
                "rate_per_night": {"lowest": "$210", "extracted_lowest": None},
            },
            {
                "source": "Agoda",
                "rate_per_night": {"lowest": "$215", "extracted_lowest": None},
            },
        ]
    }

    result = _extract_ota_prices(raw)
    assert [r["source"] for r in result] == ["Booking.com", "Expedia", "Agoda"]


# ---------------------------------------------------------------------------
# _night_count
# ---------------------------------------------------------------------------


def test_night_count_basic():
    assert _night_count("2025-06-01", "2025-06-05") == 4


def test_night_count_same_day_returns_1():
    assert _night_count("2025-06-01", "2025-06-01") == 1


def test_night_count_invalid_dates_returns_1():
    assert _night_count("bad-date", "also-bad") == 1


# ---------------------------------------------------------------------------
# search_hotels — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_returns_normalized_list(mock_gs):
    mock_gs.return_value.get_dict.return_value = {"properties": [RAW_HOTEL]}
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "hotels" in result
    assert len(result["hotels"]) == 1
    assert result["hotels"][0]["name"] == "Grand Palace Hotel"


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_persists_to_session_state(mock_gs):
    mock_gs.return_value.get_dict.return_value = {"properties": [RAW_HOTEL]}
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        await search_hotels(HOTEL_REQUEST, ctx)

    assert "last_hotel_search" in ctx.state
    payload = ctx.state["last_hotel_search"]
    assert payload["destination"] == "Tokyo, Japan"
    assert payload["check_in_date"] == "2025-06-01"
    assert payload["check_out_date"] == "2025-06-05"
    assert payload["adults"] == 2
    assert payload["nights"] == 4
    assert len(payload["results"]) == 1
    assert ctx.state["last_hotel_search_count"] == 1


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_applies_max_price_filter(mock_gs):
    cheap = {
        **RAW_HOTEL,
        "name": "Budget Inn",
        "rate_per_night": {"lowest": "$80", "extracted_lowest": 80},
    }
    expensive = {
        **RAW_HOTEL,
        "name": "Luxury Suites",
        "rate_per_night": {"lowest": "$500", "extracted_lowest": 500},
    }
    mock_gs.return_value.get_dict.return_value = {"properties": [cheap, expensive]}
    ctx = _make_tool_context()

    request = HotelSearchRequest(
        destination="Tokyo, Japan",
        check_in_date="2025-06-01",
        check_out_date="2025-06-05",
        adults=2,
        max_price=100,
    )
    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(request, ctx)

    names = [h["name"] for h in result["hotels"]]
    assert "Budget Inn" in names
    assert "Luxury Suites" not in names


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_empty_properties(mock_gs):
    mock_gs.return_value.get_dict.return_value = {"properties": []}
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert result == {"hotels": []}
    assert ctx.state["last_hotel_search_count"] == 0


# ---------------------------------------------------------------------------
# search_hotels — missing API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_hotels_no_api_key_returns_error():
    ctx = _make_tool_context(
        {
            "last_hotel_search": {
                "results": [{"name": "Old Hotel"}],
                "destination": "Old",
            }
        }
    )
    ctx.state["last_hotel_search_count"] = 1
    with patch.dict("os.environ", {}, clear=True):
        # Ensure SERP_API_KEY is not set
        import os

        os.environ.pop("SERP_API_KEY", None)
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "error" in result
    assert ctx.state["last_hotel_search_count"] == 0
    assert ctx.state["last_hotel_search"]["results"] == []
    assert ctx.state["last_hotel_search"]["destination"] == HOTEL_REQUEST.destination


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_exception_clears_stale_state(mock_gs):
    ctx = _make_tool_context(
        {
            "last_hotel_search": {
                "results": [{"name": "Old Hotel"}],
                "destination": "Old",
            }
        }
    )
    ctx.state["last_hotel_search_count"] = 1
    mock_gs.return_value.get_dict.side_effect = Exception("boom")

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "error" in result
    assert ctx.state["last_hotel_search_count"] == 0
    assert ctx.state["last_hotel_search"]["results"] == []
    assert ctx.state["last_hotel_search"]["destination"] == HOTEL_REQUEST.destination


@pytest.mark.asyncio
async def test_search_hotels_uses_api_key_from_state():
    """Session state key takes priority over environment variable."""
    ctx = _make_tool_context({"user_serp_api_key": "state-key"})
    with (
        patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch") as mock_gs,
        patch.dict("os.environ", {"SERP_API_KEY": "env-key"}),
    ):
        mock_gs.return_value.get_dict.return_value = {"properties": [RAW_HOTEL]}
        await search_hotels(HOTEL_REQUEST, ctx)
        call_params = mock_gs.call_args[0][0]
        assert call_params["api_key"] == "state-key"


# ---------------------------------------------------------------------------
# search_hotels — no tool_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_without_tool_context(mock_gs):
    mock_gs.return_value.get_dict.return_value = {"properties": [RAW_HOTEL]}

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, None)

    assert "hotels" in result
    assert len(result["hotels"]) == 1


# ---------------------------------------------------------------------------
# search_hotels — pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_follows_next_page_token(mock_gs):
    """Additional pages are fetched when next_page_token is present."""
    hotel_p1 = {**RAW_HOTEL, "serpapi_property_id": "P1", "name": "Hotel Page1"}
    hotel_p2 = {**RAW_HOTEL, "serpapi_property_id": "P2", "name": "Hotel Page2"}

    mock_gs.return_value.get_dict.side_effect = [
        # Page 1 — includes a pagination token pointing to page 2
        {
            "properties": [hotel_p1],
            "serpapi_pagination": {"next_page_token": "tok_page2"},
        },
        # Page 2 — no further token → stop
        {
            "properties": [hotel_p2],
            "serpapi_pagination": {},
        },
    ]
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "hotels" in result
    names = [h["name"] for h in result["hotels"]]
    assert "Hotel Page1" in names
    assert "Hotel Page2" in names
    # GoogleSearch must have been instantiated twice (once per page)
    assert mock_gs.call_count == 2
    # Second call must carry the next_page_token
    second_call_params = mock_gs.call_args_list[1][0][0]
    assert second_call_params["next_page_token"] == "tok_page2"


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_deduplicates_across_pages(mock_gs):
    """Properties that appear on multiple pages are kept only once."""
    duplicate = {**RAW_HOTEL, "serpapi_property_id": "DUP", "name": "Duplicate Hotel"}
    unique_p2 = {**RAW_HOTEL, "serpapi_property_id": "UNIQ", "name": "Unique Page2"}

    mock_gs.return_value.get_dict.side_effect = [
        {
            "properties": [duplicate],
            "serpapi_pagination": {"next_page_token": "tok_page2"},
        },
        {
            # 'duplicate' reappears on page 2; 'unique_p2' is new
            "properties": [duplicate, unique_p2],
            "serpapi_pagination": {},
        },
    ]
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "hotels" in result
    names = [h["name"] for h in result["hotels"]]
    assert names.count("Duplicate Hotel") == 1
    assert "Unique Page2" in names
    assert len(result["hotels"]) == 2


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_page2_exception_returns_page1_results(mock_gs):
    """An exception on page 2+ returns whatever was collected on earlier pages."""
    hotel_p1 = {**RAW_HOTEL, "serpapi_property_id": "P1", "name": "Hotel Page1"}

    mock_gs.return_value.get_dict.side_effect = [
        # Page 1 succeeds and advertises a second page
        {
            "properties": [hotel_p1],
            "serpapi_pagination": {"next_page_token": "tok_page2"},
        },
        # Page 2 raises a network-style exception
        Exception("network timeout"),
    ]
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    # Must still return the page-1 hotel, not an error dict
    assert "hotels" in result
    assert "error" not in result
    assert len(result["hotels"]) == 1
    assert result["hotels"][0]["name"] == "Hotel Page1"
    # State must reflect the partial result
    assert ctx.state["last_hotel_search_count"] == 1


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_page1_exception_returns_error_and_clears_state(mock_gs):
    """An exception on page 1 returns an error dict and resets session state."""
    ctx = _make_tool_context(
        {
            "last_hotel_search": {"results": [{"name": "Stale"}], "destination": "Old"},
            "last_hotel_search_count": 1,
        }
    )
    mock_gs.return_value.get_dict.side_effect = Exception("connection refused")

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels(HOTEL_REQUEST, ctx)

    assert "error" in result
    assert "hotels" not in result
    assert ctx.state["last_hotel_search"]["results"] == []
    assert ctx.state["last_hotel_search_count"] == 0


# ---------------------------------------------------------------------------
# search_hotels_with_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("adk_quality_lab_wiring.tools.hotel_search.GoogleSearch")
async def test_search_hotels_with_count_returns_total_count(mock_gs):
    # Use distinct serpapi_property_id values so deduplication doesn't collapse
    # the three properties into one (correct behaviour when the same hotel
    # appears on multiple pagination pages, but wrong for a fresh result set).
    hotel_a = {**RAW_HOTEL, "serpapi_property_id": "PROP_A", "name": "Hotel A"}
    hotel_b = {**RAW_HOTEL, "serpapi_property_id": "PROP_B", "name": "Hotel B"}
    hotel_c = {**RAW_HOTEL, "serpapi_property_id": "PROP_C", "name": "Hotel C"}
    mock_gs.return_value.get_dict.return_value = {
        "properties": [hotel_a, hotel_b, hotel_c]
    }
    ctx = _make_tool_context()

    with patch.dict("os.environ", {"SERP_API_KEY": "test-key"}):
        result = await search_hotels_with_count(HOTEL_REQUEST, ctx)

    assert result == {"total_count": 3}


@pytest.mark.asyncio
async def test_search_hotels_with_count_propagates_error():
    ctx = _make_tool_context()
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("SERP_API_KEY", None)
        result = await search_hotels_with_count(HOTEL_REQUEST, ctx)

    assert "error" in result
    assert "total_count" not in result


# ---------------------------------------------------------------------------
# HotelSearchSummary schema
# ---------------------------------------------------------------------------


def test_hotel_search_summary_model():
    s = HotelSearchSummary(total_found=10, search_params="Tokyo · Jun 1–5 · 2 adults")
    assert s.total_found == 10
    assert s.search_params == "Tokyo · Jun 1–5 · 2 adults"


def test_hotel_search_summary_defaults():
    s = HotelSearchSummary(total_found=0)
    assert s.search_params == ""


# ---------------------------------------------------------------------------
# get_hotel_context
# ---------------------------------------------------------------------------

HOTELS_IN_STATE = [
    {
        "name": "Park Hyatt Tokyo",
        "overall_rating": 4.8,
        "price_per_night_num": 450.0,
        "hotel_class": "5-star hotel",
    },
    {
        "name": "Shinjuku Granbell Hotel",
        "overall_rating": 4.2,
        "price_per_night_num": 150.0,
        "hotel_class": "3-star hotel",
    },
    {
        "name": "Marriott Tokyo",
        "overall_rating": 4.5,
        "price_per_night_num": 300.0,
        "hotel_class": "4-star hotel",
    },
    {
        "name": "Budget Inn",
        "overall_rating": 3.8,
        "price_per_night_num": None,  # price unavailable
        "hotel_class": "",
    },
]


def _make_hotel_tool_context(hotels: list[dict] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.state = {
        "last_hotel_search": {
            "results": hotels if hotels is not None else HOTELS_IN_STATE
        }
    }
    return ctx


def test_get_hotel_context_no_filter_returns_all():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(tool_context=ctx)
    assert len(result) == 4


def test_get_hotel_context_name_filter_case_insensitive():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(name="park hyatt", tool_context=ctx)
    assert len(result) == 1
    assert result[0]["name"] == "Park Hyatt Tokyo"


def test_get_hotel_context_name_filter_partial_match():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(name="marriott", tool_context=ctx)
    assert len(result) == 1
    assert result[0]["name"] == "Marriott Tokyo"


def test_get_hotel_context_max_price_filter():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(max_price=200.0, tool_context=ctx)
    # Shinjuku (150) + Budget Inn (None — kept) should pass; Park Hyatt (450) and Marriott (300) excluded
    names = {h["name"] for h in result}
    assert "Shinjuku Granbell Hotel" in names
    assert "Budget Inn" in names
    assert "Park Hyatt Tokyo" not in names
    assert "Marriott Tokyo" not in names


def test_get_hotel_context_min_rating_filter():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(min_rating=4.5, tool_context=ctx)
    names = {h["name"] for h in result}
    assert "Park Hyatt Tokyo" in names
    assert "Marriott Tokyo" in names
    assert "Shinjuku Granbell Hotel" not in names
    assert "Budget Inn" not in names


def test_get_hotel_context_hotel_class_filter():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(hotel_class=5, tool_context=ctx)
    assert len(result) == 1
    assert result[0]["name"] == "Park Hyatt Tokyo"


def test_get_hotel_context_combined_filters():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(min_rating=4.0, max_price=350.0, tool_context=ctx)
    names = {h["name"] for h in result}
    assert "Shinjuku Granbell Hotel" in names
    assert "Marriott Tokyo" in names
    assert "Park Hyatt Tokyo" not in names  # price 450 > 350
    assert "Budget Inn" not in names  # rating 3.8 < 4.0


def test_get_hotel_context_no_match_returns_empty():
    ctx = _make_hotel_tool_context()
    result = get_hotel_context(name="Ritz Carlton", tool_context=ctx)
    assert result == []


def test_get_hotel_context_no_state_returns_empty():
    ctx = MagicMock()
    ctx.state = {}
    result = get_hotel_context(tool_context=ctx)
    assert result == []


def test_get_hotel_context_no_tool_context_returns_empty():
    result = get_hotel_context(tool_context=None)
    assert result == []


def test_get_hotel_context_empty_results_list():
    ctx = _make_hotel_tool_context(hotels=[])
    result = get_hotel_context(tool_context=ctx)
    assert result == []


# ---------------------------------------------------------------------------
# _parse_hotel_class
# ---------------------------------------------------------------------------


def test_parse_hotel_class_int():
    assert _parse_hotel_class(5) == 5


def test_parse_hotel_class_float():
    assert _parse_hotel_class(4.0) == 4


def test_parse_hotel_class_string_with_text():
    assert _parse_hotel_class("5-star hotel") == 5


def test_parse_hotel_class_plain_string():
    assert _parse_hotel_class("4") == 4


def test_parse_hotel_class_empty_string():
    assert _parse_hotel_class("") == 0


def test_parse_hotel_class_none():
    assert _parse_hotel_class(None) == 0


# ---------------------------------------------------------------------------
# _coerce_price
# ---------------------------------------------------------------------------


def test_coerce_price_int():
    assert _coerce_price(150) == 150.0


def test_coerce_price_float():
    assert _coerce_price(149.99) == 149.99


def test_coerce_price_numeric_string():
    """SerpAPI may return extracted_lowest as a string."""
    assert _coerce_price("200") == 200.0
    assert _coerce_price("99.50") == 99.50


def test_coerce_price_non_numeric_string_returns_none():
    """Non-numeric strings must not raise TypeError — return None instead."""
    assert _coerce_price("N/A") is None
    assert _coerce_price("") is None
    assert _coerce_price("on request") is None


def test_coerce_price_none_returns_none():
    assert _coerce_price(None) is None


def test_coerce_price_unexpected_type_returns_none():
    assert _coerce_price([150]) is None


# ---------------------------------------------------------------------------
# max_price filter with string price_per_night_num values
# ---------------------------------------------------------------------------


@pytest.fixture()
def _tool_ctx_with_string_prices():
    """ToolContext whose last_hotel_search contains string-valued price_per_night_num."""
    ctx = MagicMock()
    ctx.state = {
        "last_hotel_search": {
            "results": [
                {
                    "name": "Budget Inn",
                    "price_per_night_num": "80",
                    "overall_rating": 3.5,
                    "hotel_class": "",
                },
                {
                    "name": "Mid Hotel",
                    "price_per_night_num": "150",
                    "overall_rating": 4.0,
                    "hotel_class": "",
                },
                {
                    "name": "Luxury Palace",
                    "price_per_night_num": "400",
                    "overall_rating": 4.8,
                    "hotel_class": "5-star hotel",
                },
                {
                    "name": "No Price Hotel",
                    "price_per_night_num": "N/A",
                    "overall_rating": 4.2,
                    "hotel_class": "",
                },
            ]
        }
    }
    return ctx


def test_max_price_filter_with_string_prices_no_type_error(
    _tool_ctx_with_string_prices,
):
    """String-valued price_per_night_num must not raise TypeError."""
    results = get_hotel_context(
        max_price=200.0, tool_context=_tool_ctx_with_string_prices
    )
    names = [h["name"] for h in results]
    assert "Budget Inn" in names
    assert "Mid Hotel" in names
    assert "Luxury Palace" not in names


def test_max_price_filter_non_numeric_price_kept(_tool_ctx_with_string_prices):
    """Hotels with non-numeric price strings are kept (unknown price = include)."""
    results = get_hotel_context(
        max_price=100.0, tool_context=_tool_ctx_with_string_prices
    )
    names = [h["name"] for h in results]
    assert "Budget Inn" in names
    assert "No Price Hotel" in names  # price is unknown — kept
    assert "Mid Hotel" not in names
