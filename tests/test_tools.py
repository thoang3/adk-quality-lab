"""Tests for tools: capture_fixtures (dry-run) and agent_runner (stub)."""

from __future__ import annotations

from pathlib import Path


def test_capture_fixtures_dry_run(tmp_path: Path, monkeypatch: object) -> None:
    """capture_all_routes in dry-run mode should return results without API calls."""
    from adk_quality_lab.tools.capture_fixtures import capture_all_routes

    results = capture_all_routes(
        routes=[("SFO", "LHR"), ("JFK", "CDG")],
        cabins=["economy"],
        date_offsets=[14],
        dry_run=True,
    )

    assert len(results) == 2
    for r in results:
        assert r["fixture_hash"]  # non-empty hash
        assert len(r["fixture_hash"]) == 24  # short key prefix
        # dry-run: may be cached but never fetches new data (count can be non-zero if cached)


def test_compute_key_deterministic() -> None:
    """Same params → same SHA-256 key."""
    from adk_quality_lab.tools.capture_fixtures import _build_flight_params, _compute_key

    p = _build_flight_params("SFO", "LHR", "2025-07-01", "economy")
    k1 = _compute_key(p)
    k2 = _compute_key(p)
    assert k1 == k2
    assert len(k1) == 64  # full SHA-256


def test_compute_key_varies_by_params() -> None:
    """Different routes → different keys."""
    from adk_quality_lab.tools.capture_fixtures import _build_flight_params, _compute_key

    p1 = _build_flight_params("SFO", "LHR", "2025-07-01", "economy")
    p2 = _build_flight_params("JFK", "LHR", "2025-07-01", "economy")
    assert _compute_key(p1) != _compute_key(p2)


def test_fixture_to_session_state_empty() -> None:
    """None payload → empty session state."""
    from adk_quality_lab.tools.agent_runner import _fixture_to_session_state

    state = _fixture_to_session_state(None)
    assert state == {}


def test_fixture_to_session_state_basic() -> None:
    """A minimal SerpAPI google_flights response is mapped to session state."""
    from adk_quality_lab.tools.agent_runner import _fixture_to_session_state

    payload = {
        "search_parameters": {"origin": "SFO", "destination": "LHR"},
        "best_flights": [
            {
                "flights": [
                    {
                        "flight_number": "AA100",
                        "airline": "American Airlines",
                        "departure_airport": {"id": "SFO", "time": "2025-07-01 09:00"},
                        "arrival_airport": {"id": "LHR", "time": "2025-07-02 05:30"},
                    }
                ],
                "layovers": [],
                "total_duration": 620,
                "price": 784,
            }
        ],
        "other_flights": [],
    }

    state = _fixture_to_session_state(payload)
    assert state["total_flights_found"] == 1
    flights = state["search_results_cash"]
    assert len(flights) == 1
    f = flights[0]
    assert f["flight_number"] == "AA100"
    assert f["carrier_code"] == "AA"
    assert f["price_usd"] == 784
    assert f["origin"] == "SFO"
    assert f["destination"] == "LHR"


def test_extract_carrier_code() -> None:
    from adk_quality_lab.tools.agent_runner import _extract_carrier_code

    assert _extract_carrier_code("AA100") == "AA"
    assert _extract_carrier_code("BA284") == "BA"
    assert _extract_carrier_code("QR701") == "QR"
    assert _extract_carrier_code("") == ""


def test_build_agent_fn_stub() -> None:
    """build_agent_fn with use_stub=True returns a working stub function."""
    from adk_quality_lab.tools.agent_runner import build_agent_fn

    fn = build_agent_fn(use_stub=True)
    response = fn("Find flights from JFK to LHR")
    assert "[STUB]" in response
