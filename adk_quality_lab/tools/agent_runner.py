"""ADK agent runner for adk-quality-lab Travel Concierge eval.

Provides build_agent_fn() which returns a Callable[str, dict | None] → str
that:
  1. Injects fixture tool payload into ADK session state
  2. Runs the Travel Concierge root_agent via google-adk InMemoryRunner
  3. Returns the final agent text response

Usage in eval.py::

    from adk_quality_lab.tools.agent_runner import build_agent_fn
    agent_fn = build_agent_fn(example_dir, surface="root")
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session-state keys used by travel_concierge
# ---------------------------------------------------------------------------

_FLIGHT_CASH_KEY = "search_results_cash"
_FLIGHT_AWARD_KEY = "search_results_award"
_HOTEL_KEY = "hotel_results"


def _fixture_to_session_state(tool_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Convert captured SerpAPI fixture to travel_concierge session state format.

    The fixture is raw SerpAPI google_flights output. The flight_search_agent
    expects a list of flights under ``search_results_cash`` session key.
    """
    if not tool_payload:
        return {}

    flights: list[dict[str, Any]] = []

    # SerpAPI google_flights response has best_flights and other_flights lists
    for section in ("best_flights", "other_flights"):
        for result in tool_payload.get(section, []):
            # Each entry may have multiple flight legs
            legs: list[dict[str, Any]] = result.get("flights", [])
            if not legs:
                continue

            first_leg = legs[0]
            last_leg = legs[-1]

            flights.append(
                {
                    "flight_number": first_leg.get("flight_number", ""),
                    "carrier": first_leg.get("airline", ""),
                    "carrier_code": _extract_carrier_code(first_leg.get("flight_number", "")),
                    "origin": first_leg.get("departure_airport", {}).get("id", ""),
                    "destination": last_leg.get("arrival_airport", {}).get("id", ""),
                    "departure_time": first_leg.get("departure_airport", {}).get("time", ""),
                    "arrival_time": last_leg.get("arrival_airport", {}).get("time", ""),
                    "stops": result.get("layovers") and len(result["layovers"]) or 0,
                    "duration": result.get("total_duration", 0),
                    "price_usd": result.get("price", 0),
                    "cabin_class": "economy",
                    "booking_token": result.get("booking_token", ""),
                }
            )

    total_count = len(
        tool_payload.get("best_flights", []) + tool_payload.get("other_flights", [])
    )

    session_state: dict[str, Any] = {
        _FLIGHT_CASH_KEY: flights,
        "total_flights_found": total_count,
        "search_params": tool_payload.get("search_parameters", {}),
    }

    return session_state


def _extract_carrier_code(flight_number: str) -> str:
    """Extract 2-letter IATA carrier code from flight number (e.g. 'AA100' → 'AA')."""
    if not flight_number:
        return ""
    # Find prefix of letters
    prefix = ""
    for ch in flight_number:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix[:2].upper()


# ---------------------------------------------------------------------------
# Async ADK runner
# ---------------------------------------------------------------------------


async def _run_agent_async(
    root_agent: Any,
    query: str,
    session_state: dict[str, Any],
    user_id: str = "eval-user",
    session_id: str = "eval-session",
) -> str:
    """Run an ADK agent asynchronously and return the final response text."""
    try:
        from google.adk.runners import InMemoryRunner  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("google-adk not installed — returning stub response")
        return f"[NO-ADK] Query: {query}"

    runner = InMemoryRunner(agent=root_agent, app_name="adk_quality_lab_eval")

    # Create session with pre-populated state
    await runner.session_service.create_session(
        app_name="adk_quality_lab_eval",
        user_id=user_id,
        session_id=session_id,
        state=session_state,
    )

    from google.genai import types as genai_types  # type: ignore[import-untyped]

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=query)],
    )

    last_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        # Collect final agent response
        if hasattr(event, "content") and event.content:
            for part in event.content.parts or []:
                if hasattr(part, "text") and part.text:
                    last_text = part.text

    return last_text or "[EMPTY AGENT RESPONSE]"


def _run_agent_sync(
    root_agent: Any,
    query: str,
    session_state: dict[str, Any],
) -> str:
    """Synchronous wrapper around _run_agent_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an event loop (e.g. Jupyter) — use nest_asyncio
            import nest_asyncio  # type: ignore[import-untyped]

            nest_asyncio.apply()
            return loop.run_until_complete(
                _run_agent_async(root_agent, query, session_state)
            )
        return loop.run_until_complete(
            _run_agent_async(root_agent, query, session_state)
        )
    except RuntimeError:
        return asyncio.run(_run_agent_async(root_agent, query, session_state))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_agent_fn(
    example_dir: str | Path | None = None,
    surface: str = "root",
    use_stub: bool = False,
) -> Any:
    """Build an agent_fn(query, tool_payload) callable for eval runner.

    Args:
        example_dir: Path to examples/travel-concierge (auto-detected if None).
        surface: Which sub-agent to target: 'root', 'planning', 'inspiration'.
        use_stub: If True, return a stub function that doesn't call the agent.
            Useful for fast CI smoke tests.

    Returns:
        Callable[[str, dict | None], str]
    """
    if use_stub:
        logger.warning("Using stub agent_fn (use_stub=True)")

        def _stub_fn(query: str, tool_payload: object = None) -> str:
            return f"[STUB] Query: {query}"

        return _stub_fn

    if example_dir is None:
        example_dir = Path(__file__).parent.parent.parent / "examples" / "travel-concierge"
    example_dir = Path(example_dir)

    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))

    # Set TRAVEL_CONCIERGE_SCENARIO to an absolute path before the agent module
    # is imported — memory.py reads this as a module-level constant at import time.
    scenario_key = "TRAVEL_CONCIERGE_SCENARIO"
    if not os.environ.get(scenario_key):
        default_scenario = (
            example_dir / "travel_concierge" / "profiles" / "itinerary_empty_default.json"
        )
        os.environ[scenario_key] = str(default_scenario.resolve())

    # Import root agent lazily to avoid import-time side effects
    root_agent = _load_root_agent(example_dir, surface)

    def agent_fn(query: str, tool_payload: dict[str, Any] | None = None) -> str:
        session_state = _fixture_to_session_state(tool_payload)
        try:
            return _run_agent_sync(root_agent, query, session_state)
        except Exception as exc:
            logger.error("Agent run failed: %s", exc, exc_info=True)
            return f"[ERROR] {exc}"

    return agent_fn


def _load_root_agent(example_dir: Path, surface: str) -> Any:
    """Load the appropriate agent object for the requested surface."""
    try:
        if surface == "root":
            from travel_concierge.agent import root_agent  # type: ignore[import-untyped]

            return root_agent
        elif surface == "planning":
            from travel_concierge.sub_agents.planning.agent import (
                planning_agent,  # type: ignore[import-untyped]
            )

            return planning_agent
        elif surface == "inspiration":
            from travel_concierge.sub_agents.inspiration.agent import (
                inspiration_agent,  # type: ignore[import-untyped]
            )

            return inspiration_agent
        else:
            logger.warning("Unknown surface '%s', falling back to root_agent", surface)
            from travel_concierge.agent import root_agent  # type: ignore[import-untyped]

            return root_agent
    except ImportError as exc:
        logger.error(
            "Could not import travel_concierge agent (is %s in sys.path?): %s",
            example_dir,
            exc,
        )
        raise
