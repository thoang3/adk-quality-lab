"""Fixture-backed flight search tool for the ADK Quality Lab eval harness.

This is the ONLY change made to enable a meaningful baseline eval:
  - The vanilla `flight_search_agent` has no tools and hallucinates flights.
  - This tool provides real SerpAPI data from pre-captured fixture files,
    so the LLM synthesizes from real data rather than generating from weights.

The fixture files live at:
  datasets/fixtures/flights/<sha256>.json

They are captured once via `make capture-fixtures` and never re-fetched during
eval — every eval run is fully deterministic and offline.

Hash computation is identical to `adk_quality_lab/tools/capture_fixtures.py`
so the same key resolves to the same file across the harness and this tool.

This module intentionally does NOT import from travel_concierge.tools.search
to keep the wiring layer simple.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixture resolution
# ---------------------------------------------------------------------------

# Repo root: parents[4] of this file:
#   tools/fixture_flight_search.py
#   adk_quality_lab_wiring/tools/
#   adk_quality_lab_wiring/
#   examples/travel-concierge/
#   examples/
#   <repo root>/                      ← parents[4]
_REPO_ROOT = Path(__file__).parents[4]
_FIXTURES_DIR = Path(
    os.environ.get("QUALITY_LAB_FIXTURES_DIR", str(_REPO_ROOT / "datasets" / "fixtures" / "flights"))
)


def _cabin_to_serpapi(cabin: str) -> str:
    """Map cabin name to SerpAPI travel_class string value."""
    return {"economy": "1", "premium_economy": "2", "business": "3", "first": "4"}.get(
        cabin.lower(), "1"
    )


def _compute_fixture_key(
    origin: str,
    destination: str,
    outbound_date: str,
    cabin_class: str = "economy",
    adults: int = 1,
    return_date: str | None = None,
) -> str:
    """Compute the SHA-256 fixture key — must match capture_fixtures._compute_key exactly."""
    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin.upper(),
        "arrival_id": destination.upper(),
        "outbound_date": outbound_date,
        "travel_class": _cabin_to_serpapi(cabin_class),
        "adults": str(adults),
        "currency": "USD",
        "hl": "en",
    }
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"  # round trip
    else:
        params["type"] = "2"  # one way
    canonical = {k: v for k, v in sorted(params.items())}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _load_fixture(key: str) -> dict[str, Any] | None:
    """Load a fixture JSON by its full SHA-256 key. Returns None if not found."""
    path = _FIXTURES_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse fixture %s: %s", path, exc)
    # Fallback: match by 24-char prefix (eval cases store truncated hashes)
    prefix = key[:24]
    for candidate in _FIXTURES_DIR.glob(f"{prefix}*.json"):
        try:
            return json.loads(candidate.read_text())
        except Exception as exc:
            logger.warning("Failed to parse fixture %s: %s", candidate, exc)
    return None


# ---------------------------------------------------------------------------
# The ADK FunctionTool callable
# ---------------------------------------------------------------------------

async def search_flights(
    origin: str,
    destination: str,
    outbound_date: str,
    cabin_class: str = "economy",
    adults: int = 1,
) -> str:
    """Search for available flights between two airports on a given date.

    Returns real flight data from Google Flights (pre-captured fixtures).
    Results include flight number, airline, departure/arrival times, price,
    and number of stops for each available flight option.

    Args:
        origin:       IATA airport code for departure (e.g. "SFO", "JFK").
        destination:  IATA airport code for arrival (e.g. "LHR", "NRT").
        outbound_date: Departure date in YYYY-MM-DD format.
        cabin_class:  One of "economy", "premium_economy", "business", "first".
        adults:       Number of adult passengers (default 1).

    Returns:
        JSON string with all available flights and a total count.
    """
    key = _compute_fixture_key(origin, destination, outbound_date, cabin_class, adults)
    fixture = _load_fixture(key)

    if fixture is None:
        logger.warning(
            "No fixture found for %s→%s %s %s (key=%s)",
            origin, destination, outbound_date, cabin_class, key[:16] + "…",
        )
        return json.dumps({
            "error": f"No flight data available for {origin}→{destination} on {outbound_date}",
            "flights": [],
            "total_count": 0,
        })

    best = fixture.get("best_flights", [])
    other = fixture.get("other_flights", [])
    all_results = best + other
    total = len(all_results)

    logger.info(
        "Fixture hit: %s→%s %s %s — %d flights (%d best + %d other)",
        origin, destination, outbound_date, cabin_class,
        total, len(best), len(other),
    )

    # Return the raw SerpAPI structure so the LLM synthesizes from real data.
    # The FlightsSelection output_schema on flight_search_agent will guide
    # the LLM to extract flight_number, departure, arrival, price, etc.
    return json.dumps({
        "total_count": total,
        "best_flights": best,
        "other_flights": other,
    })


async def search_flights_range(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    cabin_class: str = "economy",
    adults: int = 1,
) -> str:
    """Search for available flights across a date range.

    Calls the per-date fixture for each calendar day from start_date to
    end_date (inclusive), then merges and deduplicates results.  This is the
    primary tool for tail/stress-test cases that produce 70–120+ ground-truth
    flights — the regime where baseline agents exhibit truncation collapse.

    Args:
        origin:      IATA airport code for departure (e.g. "SFO", "JFK").
        destination: IATA airport code for arrival (e.g. "LHR", "NRT").
        start_date:  First departure date in YYYY-MM-DD format.
        end_date:    Last departure date in YYYY-MM-DD format (inclusive).
        cabin_class: One of "economy", "premium_economy", "business", "first".
        adults:      Number of adult passengers (default 1).

    Returns:
        JSON string with all available flights merged across the date range,
        deduplicated by (flight_number, outbound_date), and a total count.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    seen: set[tuple[str, str]] = set()
    merged_best: list[dict[str, Any]] = []
    merged_other: list[dict[str, Any]] = []
    missing_dates: list[str] = []

    current = start
    while current <= end:
        day_str = current.isoformat()
        key = _compute_fixture_key(origin, destination, day_str, cabin_class, adults)
        fixture = _load_fixture(key)

        if fixture is None:
            logger.warning(
                "No fixture for %s→%s %s %s (key=%s)",
                origin, destination, day_str, cabin_class, key[:16] + "…",
            )
            missing_dates.append(day_str)
            current += timedelta(days=1)
            continue

        for flight in fixture.get("best_flights", []):
            dedup_key = (flight.get("flight_number", ""), day_str)
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged_best.append({**flight, "outbound_date": day_str})

        for flight in fixture.get("other_flights", []):
            dedup_key = (flight.get("flight_number", ""), day_str)
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged_other.append({**flight, "outbound_date": day_str})

        current += timedelta(days=1)

    total = len(merged_best) + len(merged_other)
    logger.info(
        "search_flights_range: %s→%s %s–%s %s — %d flights across %d dates (%d missing)",
        origin, destination, start_date, end_date, cabin_class,
        total, (end - start).days + 1, len(missing_dates),
    )

    result: dict[str, Any] = {
        "total_count": total,
        "best_flights": merged_best,
        "other_flights": merged_other,
    }
    if missing_dates:
        result["missing_dates"] = missing_dates
    return json.dumps(result)
