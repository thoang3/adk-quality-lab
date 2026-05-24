"""Generate expanded F1 and F2 eval case sets from captured fixtures.

Usage:
    python -m adk_quality_lab.tools.generate_cases --f1-count=50 --f2-count=50
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_FIXTURES_DIR = _REPO_ROOT / "datasets" / "fixtures" / "flights"
_DATASETS_DIR = _REPO_ROOT / "datasets"
_INDEX_PATH = _REPO_ROOT / "datasets" / "fixtures" / "index.json"

# F1: count hallucination — agent claims wrong number of flights
_F1_DIFFICULTIES = ["easy", "medium", "hard"]

# F2: groundedness — agent cites values not in the tool payload
_F2_DIFFICULTIES = ["easy", "medium", "hard"]

# Query templates for F1
_F1_QUERY_TEMPLATES = [
    "Find flights from {origin} to {destination} in economy class",
    "Show me all available flights from {origin} to {destination}",
    "How many flights are available from {origin} to {destination}?",
    "Search for flights from {origin} to {destination}",
    "What flights go from {origin} to {destination}?",
    "Find me options for traveling from {origin} to {destination}",
    "I need to fly from {origin} to {destination}, what are my choices?",
    "List all flights between {origin} and {destination}",
    "What airlines fly between {origin} and {destination}?",
    "Compare all flights from {origin} to {destination}",
]

# Query templates for F2
_F2_QUERY_TEMPLATES = [
    "Find the cheapest flight from {origin} to {destination}",
    "What is the best deal for a flight from {origin} to {destination}?",
    "Show me the lowest priced flight from {origin} to {destination}",
    "Find a direct flight from {origin} to {destination}",
    "What is the price of the cheapest economy flight from {origin} to {destination}?",
    "I want to book the most affordable flight from {origin} to {destination}",
    "Find me a flight on {carrier} from {origin} to {destination}",
    "What does the {cabin} class flight from {origin} to {destination} cost?",
    "Book me the best value flight from {origin} to {destination}",
    "What is the cheapest {cabin} flight from {origin} to {destination}?",
]

_F1_RATERS = [
    "deterministic.row_count_match",
    "deterministic.iata_membership",
    "llm_judge.truncation_disclosure",
]

_F2_RATERS = [
    "deterministic.iata_membership",
    "deterministic.numerical_equality",
    "groundedness.structured_value",
    "llm_judge.value_groundedness",
]


def _load_index() -> dict[str, dict]:
    if _INDEX_PATH.exists():
        return json.loads(_INDEX_PATH.read_text())
    return {}


def _load_fixture(full_hash: str) -> dict | None:
    path = _FIXTURES_DIR / f"{full_hash}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _get_short_hash(full_hash: str) -> str:
    return full_hash[:24]


def _extract_best_flight(fixture: dict) -> dict | None:
    best = fixture.get("best_flights") or fixture.get("other_flights") or []
    if not best:
        return None
    first = best[0]
    legs = first.get("flights", [])
    if not legs:
        return None
    leg = legs[0]
    return {
        "flight_number": leg.get("flight_number", ""),
        "carrier": (leg.get("flight_number") or "")[:2],
        "price": first.get("price", 0),
        "cabin": "economy",
        "stops": len(first.get("layovers", [])),
    }


def _count_flights(fixture: dict) -> int:
    return len(fixture.get("best_flights", []) + fixture.get("other_flights", []))


def generate_f1_cases(target: int = 50) -> list[dict]:
    """Generate F1 count-hallucination eval cases from captured fixtures."""
    index = _load_index()
    cases: list[dict] = []
    seen_hashes: set[str] = set()

    query_idx = 0
    diff_cycle = _F1_DIFFICULTIES * 20  # enough for 50+

    for full_hash, meta in sorted(index.items()):
        if len(cases) >= target:
            break
        if full_hash in seen_hashes:
            continue

        fixture = _load_fixture(full_hash)
        if not fixture:
            continue

        count = _count_flights(fixture)
        if count == 0:
            continue

        origin = meta["origin"]
        destination = meta["destination"]
        cabin = meta.get("cabin", "economy")
        short_hash = _get_short_hash(full_hash)

        template = _F1_QUERY_TEMPLATES[query_idx % len(_F1_QUERY_TEMPLATES)]
        query = template.format(origin=origin, destination=destination)
        difficulty = diff_cycle[len(cases)]

        case_id = f"f1_{len(cases) + 1:03d}"
        cases.append({
            "case_id": case_id,
            "category": "F1",
            "difficulty": difficulty,
            "query": query,
            "fixture_hash": short_hash,
            "raters": _F1_RATERS,
            "expected_flight_count": count,
            "route": f"{origin}-{destination}",
            "cabin": cabin,
            "departure_date": meta.get("departure_date", ""),
        })
        seen_hashes.add(full_hash)
        query_idx += 1

    logger.info("Generated %d F1 cases", len(cases))
    return cases


def generate_f2_cases(target: int = 50) -> list[dict]:
    """Generate F2 groundedness eval cases from captured fixtures."""
    index = _load_index()
    cases: list[dict] = []
    seen_hashes: set[str] = set()

    query_idx = 0
    diff_cycle = _F2_DIFFICULTIES * 20

    for full_hash, meta in sorted(index.items()):
        if len(cases) >= target:
            break
        if full_hash in seen_hashes:
            continue

        fixture = _load_fixture(full_hash)
        if not fixture:
            continue

        best_flight = _extract_best_flight(fixture)
        if not best_flight or not best_flight["flight_number"]:
            continue

        origin = meta["origin"]
        destination = meta["destination"]
        cabin = meta.get("cabin", "economy")
        short_hash = _get_short_hash(full_hash)

        template = _F2_QUERY_TEMPLATES[query_idx % len(_F2_QUERY_TEMPLATES)]
        query = template.format(
            origin=origin,
            destination=destination,
            carrier=best_flight["carrier"],
            cabin=cabin,
        )

        difficulty = diff_cycle[len(cases)]
        case_id = f"f2_{len(cases) + 1:03d}"
        price = best_flight["price"]
        price_str = f"{float(price):.2f}" if price else ""

        cases.append({
            "case_id": case_id,
            "category": "F2",
            "difficulty": difficulty,
            "query": query,
            "fixture_hash": short_hash,
            "raters": _F2_RATERS,
            "expected_values": {
                "carrier": best_flight["carrier"],
                "flight_number": best_flight["flight_number"],
                "price": price_str,
            },
            "route": f"{origin}-{destination}",
            "cabin": cabin,
            "departure_date": meta.get("departure_date", ""),
        })
        seen_hashes.add(full_hash)
        query_idx += 1

    logger.info("Generated %d F2 cases", len(cases))
    return cases


def write_jsonl(cases: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    logger.info("Wrote %d cases to %s", len(cases), path)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate eval case sets from fixtures")
    parser.add_argument("--f1-count", type=int, default=50)
    parser.add_argument("--f2-count", type=int, default=50)
    parser.add_argument("--out-dir", default=str(_DATASETS_DIR))
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)

    f1_cases = generate_f1_cases(args.f1_count)
    write_jsonl(f1_cases, out_dir / "f1_count_hallucination.jsonl")

    f2_cases = generate_f2_cases(args.f2_count)
    write_jsonl(f2_cases, out_dir / "f2_groundedness.jsonl")

    print(f"✓ {len(f1_cases)} F1 cases → {out_dir}/f1_count_hallucination.jsonl")
    print(f"✓ {len(f2_cases)} F2 cases → {out_dir}/f2_groundedness.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
