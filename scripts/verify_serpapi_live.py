#!/usr/bin/env python3
"""Minimal live SerpAPI verifier for adk-quality-lab.

Purpose:
- Confirm whether a real `google_flights` SerpAPI call works in this repo/env.
- Write full debug output to a log file for inspection.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import requests


LOGGER = logging.getLogger("verify_serpapi_live")


def _configure_logging(log_file: str, log_level: str) -> Path:
    log_path = Path(log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
    )
    LOGGER.info("Writing logs to %s", log_path)
    return log_path


def _extract_summary(payload: dict[str, Any]) -> dict[str, Any]:
    best = payload.get("best_flights") or []
    other = payload.get("other_flights") or []
    first = (best + other)[0] if (best or other) else {}
    first_leg = (first.get("flights") or [{}])[0] if first else {}
    return {
        "best_count": len(best),
        "other_count": len(other),
        "first_airline": first_leg.get("airline"),
        "first_flight_number": first_leg.get("flight_number"),
        "first_departure_time": (first_leg.get("departure_airport") or {}).get("time"),
        "first_arrival_time": (first_leg.get("arrival_airport") or {}).get("time"),
        "search_metadata_status": (payload.get("search_metadata") or {}).get("status"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify live SerpAPI google_flights call")
    parser.add_argument("--origin", default="SFO")
    parser.add_argument("--destination", default="NRT")
    parser.add_argument("--date", default="2026-09-12", help="Outbound date YYYY-MM-DD")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--hl", default="en")
    parser.add_argument("--trip-type", default="2", choices=["1", "2"], help="1=roundtrip, 2=one-way")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", default="backend.log")
    parser.add_argument("--dump-json", default="serpapi_response.json", help="Path to write raw response JSON")
    args = parser.parse_args()

    _configure_logging(args.log_file, args.log_level)

    api_key = os.getenv("SERP_API_KEY")
    if not api_key:
        LOGGER.error("SERP_API_KEY is not set. Export it or add it to your environment.")
        sys.exit(2)

    params = {
        "engine": "google_flights",
        "departure_id": args.origin,
        "arrival_id": args.destination,
        "outbound_date": args.date,
        "currency": args.currency,
        "hl": args.hl,
        "api_key": api_key,
        "type": args.trip_type,
    }
    LOGGER.info("Calling SerpAPI: %s -> %s on %s", args.origin, args.destination, args.date)

    response = requests.get("https://serpapi.com/search", params=params, timeout=args.timeout)
    LOGGER.info("HTTP status: %s", response.status_code)

    payload = response.json()
    Path(args.dump_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOGGER.info("Raw JSON saved to %s", Path(args.dump_json).resolve())

    if response.status_code != 200:
        LOGGER.error("Non-200 response body: %s", json.dumps(payload)[:1200])
        sys.exit(1)

    if payload.get("error"):
        LOGGER.error("SerpAPI error: %s", payload.get("error"))
        sys.exit(1)

    summary = _extract_summary(payload)
    LOGGER.info("Result summary: %s", summary)

    if summary["best_count"] == 0 and summary["other_count"] == 0:
        LOGGER.warning("Call succeeded but returned zero flights for this route/date.")
        sys.exit(3)

    LOGGER.info("✅ Live SerpAPI call works and returned flight data.")


if __name__ == "__main__":
    main()
