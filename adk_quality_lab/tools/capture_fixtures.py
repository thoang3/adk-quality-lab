"""Fixture capture tool for adk-quality-lab.

Calls SerpAPI google_flights engine directly and saves deterministic
fixture JSON files to datasets/fixtures/flights/<sha256>.json.

Usage:
    python -m adk_quality_lab.tools.capture_fixtures --routes=all
    python -m adk_quality_lab.tools.capture_fixtures --routes=SFO-LHR,JFK-LHR
    python -m adk_quality_lab.tools.capture_fixtures --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_FIXTURES_DIR = _REPO_ROOT / "datasets" / "fixtures" / "flights"
_INDEX_PATH = _REPO_ROOT / "datasets" / "fixtures" / "index.json"
_DATASETS_DIR = _REPO_ROOT / "datasets"

# Routes to capture: all seed routes from F1 + F2 datasets
_DEFAULT_ROUTES = [
    ("SFO", "LHR"),
    ("JFK", "LHR"),
    ("JFK", "CDG"),
    ("ORD", "NRT"),
    ("LAX", "NRT"),
    ("SFO", "HKG"),
    ("JFK", "DXB"),
    ("ORD", "LHR"),
    ("SFO", "NRT"),
    ("LAX", "HND"),
    # F2 additional routes
    ("JFK", "SFO"),
    ("LAX", "JFK"),
    ("ORD", "MIA"),
    ("SFO", "ORD"),
    ("BOS", "LAX"),
]

# Cabin classes to capture for each route
_CABIN_CLASSES = ["economy", "business"]

# Number of future date offsets to capture (from today)
_DATE_OFFSETS_DAYS = [14, 30, 60]


# ---------------------------------------------------------------------------
# SerpAPI helpers
# ---------------------------------------------------------------------------


def _serpapi_available() -> bool:
    try:
        import serpapi  # noqa: F401  # type: ignore[import-untyped]

        return True
    except ImportError:
        return False


def _query_serpapi(
    params: dict[str, Any], retries: int = 3, backoff: float = 5.0
) -> dict[str, Any]:
    """Call SerpAPI google_flights engine with given params.

    Retries up to `retries` times on network/timeout errors with exponential backoff.
    """
    import time

    from serpapi.google_search import GoogleSearch  # type: ignore[import-untyped]

    api_key = os.environ.get("SERP_API_KEY") or os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SERP_API_KEY or SERPAPI_API_KEY environment variable is not set. "
            "Set it in your .env file or export it."
        )
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            search = GoogleSearch({**params, "api_key": api_key})
            return dict(search.get_dict())
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff * attempt
                logger.warning(
                    "SerpAPI attempt %d/%d failed (%s) — retrying in %.0fs",
                    attempt, retries, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error("SerpAPI failed after %d attempts: %s", retries, exc)
    raise RuntimeError(f"SerpAPI failed after {retries} attempts") from last_exc


def _cabin_to_serpapi(cabin: str) -> str:
    """Map internal cabin name to SerpAPI travel_class value."""
    mapping = {
        "economy": "1",
        "premium_economy": "2",
        "business": "3",
        "first": "4",
    }
    return mapping.get(cabin.lower(), "1")


def _build_flight_params(
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str,
    return_date: str | None = None,
    adults: int = 1,
) -> dict[str, Any]:
    """Build SerpAPI google_flights params dict."""
    params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "travel_class": _cabin_to_serpapi(cabin),
        "adults": str(adults),
        "currency": "USD",
        "hl": "en",
    }
    if return_date:
        params["return_date"] = return_date
        params["type"] = "1"  # round trip
    else:
        params["type"] = "2"  # one way
    return params


# ---------------------------------------------------------------------------
# Caching + indexing
# ---------------------------------------------------------------------------


def _compute_key(params: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 key from canonical params."""
    # Exclude api_key from hash
    canonical = {k: v for k, v in sorted(params.items()) if k != "api_key"}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _load_index() -> dict[str, Any]:
    if _INDEX_PATH.exists():
        return json.loads(_INDEX_PATH.read_text())
    return {}


def _save_index(index: dict[str, Any]) -> None:
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True))


def _fixture_path(key: str) -> Path:
    return _FIXTURES_DIR / f"{key}.json"


def _save_fixture(key: str, data: dict[str, Any]) -> Path:
    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = _fixture_path(key)
    path.write_text(json.dumps(data, indent=2))
    return path


# ---------------------------------------------------------------------------
# Core capture logic
# ---------------------------------------------------------------------------


def capture_route(
    origin: str,
    destination: str,
    departure_date: str,
    cabin: str = "economy",
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Capture a single flight search fixture.

    Returns a dict with:
        fixture_hash: SHA-256 key (24-char prefix)
        fixture_hash_full: full 64-char SHA-256
        params: the SerpAPI params used
        cached: whether we hit an existing fixture
        count: number of flight results
    """
    params = _build_flight_params(origin, destination, departure_date, cabin)
    key = _compute_key(params)
    short_key = key[:24]

    existing = _fixture_path(key)
    if existing.exists() and not force:
        data = json.loads(existing.read_text())
        count = len(data.get("best_flights", []) + data.get("other_flights", []))
        logger.info(
            "  ↩ cached %s  %s→%s %s %s  (%d results)",
            short_key, origin, destination, departure_date, cabin, count,
        )
        return {
            "fixture_hash": short_key,
            "fixture_hash_full": key,
            "params": params,
            "cached": True,
            "count": count,
        }

    if dry_run:
        logger.info(
            "  [DRY] would capture %s→%s %s %s  key=%s",
            origin, destination, departure_date, cabin, short_key,
        )
        return {
            "fixture_hash": short_key,
            "fixture_hash_full": key,
            "params": params,
            "cached": False,
            "count": 0,
        }

    logger.info("  ⬇ fetching  %s→%s %s %s ...", origin, destination, departure_date, cabin)
    data = _query_serpapi(params)

    count = len(data.get("best_flights", []) + data.get("other_flights", []))
    path = _save_fixture(key, data)
    logger.info("    ✓ %d results → %s", count, path.name)

    return {
        "fixture_hash": short_key,
        "fixture_hash_full": key,
        "params": params,
        "cached": False,
        "count": count,
    }


def capture_all_routes(
    routes: list[tuple[str, str]] | None = None,
    cabins: list[str] | None = None,
    date_offsets: list[int] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Capture fixtures for all routes × cabins × dates.

    Returns a list of result dicts, one per (route, cabin, date) combination.
    Also updates datasets/fixtures/index.json with key → human description mapping.
    """
    routes = routes or _DEFAULT_ROUTES
    cabins = cabins or _CABIN_CLASSES
    date_offsets = date_offsets or _DATE_OFFSETS_DAYS

    today = date.today()
    results: list[dict[str, Any]] = []
    index = _load_index()

    for origin, destination in routes:
        for cabin in cabins:
            for offset in date_offsets:
                dep_date = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
                r = capture_route(
                    origin, destination, dep_date, cabin,
                    dry_run=dry_run, force=force,
                )
                r["origin"] = origin
                r["destination"] = destination
                r["departure_date"] = dep_date
                r["cabin"] = cabin
                results.append(r)

                if not dry_run:
                    index[r["fixture_hash_full"]] = {
                        "short": r["fixture_hash"],
                        "origin": origin,
                        "destination": destination,
                        "departure_date": dep_date,
                        "cabin": cabin,
                        "count": r["count"],
                    }

    if not dry_run:
        _save_index(index)
        logger.info("Index saved: %d entries", len(index))

    return results


# ---------------------------------------------------------------------------
# Dataset fixture-hash patcher
# ---------------------------------------------------------------------------


def patch_dataset_hashes(
    results: list[dict[str, Any]],
    dataset_path: Path,
) -> int:
    """Patch placeholder fixture_hash values in a JSONL dataset file.

    Replaces entries where fixture_hash starts with 'placeholder_' with the
    real SHA-256 hash from the captured fixtures index, matched on
    origin/destination/cabin fields.

    Returns the number of cases patched.
    """
    if not dataset_path.exists():
        logger.warning("Dataset not found: %s", dataset_path)
        return 0

    # Build lookup: (origin, dest, cabin) → short hash
    lookup: dict[tuple[str, str, str], str] = {}
    for r in results:
        key = (r["origin"], r["destination"], r.get("cabin", "economy"))
        # Prefer economy key as default
        if key not in lookup or r.get("cabin") == "economy":
            lookup[key] = r["fixture_hash"]

    lines = dataset_path.read_text().splitlines()
    patched_lines: list[str] = []
    patched_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            patched_lines.append(line)
            continue
        case = json.loads(line)
        if case.get("fixture_hash", "").startswith("placeholder_"):
            # Try to find a matching fixture
            # Look in the "query" field for IATA codes
            query = case.get("query", "")
            matched = False
            for (orig, dest, _cabin), hash_val in lookup.items():
                if orig in query and dest in query:
                    case["fixture_hash"] = hash_val
                    patched_count += 1
                    matched = True
                    break
            if not matched:
                logger.warning(
                    "Could not find fixture for case %s: %s",
                    case.get("case_id"),
                    query,
                )
        patched_lines.append(json.dumps(case))

    dataset_path.write_text("\n".join(patched_lines) + "\n")
    logger.info("Patched %d cases in %s", patched_count, dataset_path.name)
    return patched_count


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _parse_routes(routes_str: str) -> list[tuple[str, str]]:
    """Parse 'SFO-LHR,JFK-CDG' into [('SFO','LHR'),('JFK','CDG')]."""
    result = []
    for pair in routes_str.split(","):
        pair = pair.strip()
        if "-" in pair:
            parts = pair.split("-")
            if len(parts) == 2:
                result.append((parts[0].strip().upper(), parts[1].strip().upper()))
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Capture SerpAPI flight fixtures for deterministic eval"
    )
    parser.add_argument(
        "--routes",
        default="all",
        help="Comma-separated IATA pairs (e.g. SFO-LHR,JFK-CDG) or 'all'",
    )
    parser.add_argument(
        "--cabins",
        default="economy,business",
        help="Comma-separated cabin classes",
    )
    parser.add_argument(
        "--date-offsets",
        default="14,30,60",
        help="Comma-separated day offsets from today",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't call API")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    parser.add_argument(
        "--patch-datasets",
        action="store_true",
        default=True,
        help="Patch placeholder fixture_hashes in JSONL datasets after capture",
    )
    args = parser.parse_args(argv)

    if not _serpapi_available() and not args.dry_run:
        logger.error("serpapi package not installed. Run: uv add serpapi")
        return 1

    routes = _DEFAULT_ROUTES if args.routes == "all" else _parse_routes(args.routes)
    cabins = [c.strip() for c in args.cabins.split(",")]
    date_offsets = [int(x.strip()) for x in args.date_offsets.split(",")]

    logger.info(
        "Capturing %d routes × %d cabins × %d dates = %d fixtures",
        len(routes),
        len(cabins),
        len(date_offsets),
        len(routes) * len(cabins) * len(date_offsets),
    )

    results = capture_all_routes(
        routes=routes,
        cabins=cabins,
        date_offsets=date_offsets,
        dry_run=args.dry_run,
        force=args.force,
    )

    total = len(results)
    fetched = sum(1 for r in results if not r["cached"] and r["count"] > 0)
    cached = sum(1 for r in results if r["cached"])

    logger.info("Done: %d total (%d fetched, %d cached)", total, fetched, cached)

    if args.patch_datasets and not args.dry_run:
        for fname in ["f1_count_hallucination.jsonl", "f2_groundedness.jsonl"]:
            patch_dataset_hashes(results, _DATASETS_DIR / fname)

    return 0


if __name__ == "__main__":
    sys.exit(main())
