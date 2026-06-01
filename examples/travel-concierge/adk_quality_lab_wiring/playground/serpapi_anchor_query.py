#!/usr/bin/env python3
"""Run the anchor SerpAPI query from scripts/test_serpapi_timezone.py (Query 1).

Anchor query:
- Route: SFO -> NRT
- Date: 2026-08-15
- Engine: google_flights
- Cabin: economy
- Type: one-way
"""

import json
import os
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    """Best-effort load of repository .env for local playground runs."""
    if load_dotenv is None:
        return
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")


def main() -> None:
    _load_env()

    api_key = os.getenv("SERP_API_KEY")
    if not api_key:
        raise SystemExit("SERP_API_KEY is not set")

    params = {
        "engine": "google_flights",
        "departure_id": "SFO",
        "arrival_id": "NRT",
        "outbound_date": "2026-08-15",
        "travel_class": "1",  # Economy
        "currency": "USD",
        "hl": "en",
        "api_key": api_key,
        "type": "2",
    }

    response = requests.get("https://serpapi.com/search", params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    best_flights = payload.get("best_flights", [])
    other_flights = payload.get("other_flights", [])
    all_flights = [*best_flights, *other_flights]

    print(f"best_flights count: {len(best_flights)}")
    print(f"other_flights count: {len(other_flights)}")
    print(f"total flights: {len(all_flights)}")

    if not all_flights:
        print(json.dumps({"error": payload.get("error"), "keys": list(payload.keys())}, indent=2))
        return

    for index, flight_option in enumerate(all_flights, start=1):
        legs = flight_option.get("flights", [])
        first_leg = legs[0] if legs else {}
        last_leg = legs[-1] if legs else {}

        dep_time = (first_leg.get("departure_airport") or {}).get("time", "N/A")
        arr_time = (last_leg.get("arrival_airport") or {}).get("time", "N/A")
        price = flight_option.get("price", "N/A")

        flight_numbers = [
            f"{leg.get('airline', '')} {leg.get('flight_number', '')}".strip()
            for leg in legs
        ]

        print("\n" + "=" * 80)
        print(f"Option {index}/{len(all_flights)}")
        print("=" * 80)
        print(f"Price: ${price}")
        print(f"Legs: {len(legs)}")
        print(f"Departure: {dep_time}")
        print(f"Arrival:   {arr_time}")
        print(f"Flights:   {', '.join(flight_numbers) if flight_numbers else 'N/A'}")
        print(json.dumps(flight_option, indent=2)[:2500])


if __name__ == "__main__":
    main()
