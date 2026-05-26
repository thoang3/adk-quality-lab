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

# ---------------------------------------------------------------------------
# 429 retry config
# ---------------------------------------------------------------------------

_RETRY_MAX_ATTEMPTS = 6        # total attempts (1 original + 5 retries)
_RETRY_BASE_DELAY_S = 5.0      # first back-off delay in seconds
_RETRY_MAX_DELAY_S  = 120.0    # cap
_RETRY_BACKOFF      = 2.0      # exponential multiplier


def _is_resource_exhausted(exc: BaseException) -> bool:
    """Return True if exc is a 429 / RESOURCE_EXHAUSTED error."""
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session-state keys used by travel_concierge
# ---------------------------------------------------------------------------

_FLIGHT_CASH_KEY = "search_results_cash"
_HOTEL_KEY = "hotel_results"


def _fixture_to_session_state(tool_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Convert captured SerpAPI fixture to travel_concierge session state.

    Loads the scenario profile as the base state (provides user_profile and all
    required template variables with safe defaults), then overlays:
      - Route fields (origin, destination, departure_date) from fixture search_parameters
      - Normalised flight list under search_results_cash
      - Current time as _time
    """
    import json
    from datetime import datetime, timezone

    # ── Base state: load scenario profile so all prompt template vars have values ──
    scenario_path = os.environ.get("TRAVEL_CONCIERGE_SCENARIO", "")
    state: dict[str, Any] = {}
    if scenario_path and Path(scenario_path).exists():
        try:
            profile = json.loads(Path(scenario_path).read_text())
            state = dict(profile.get("state", {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load scenario profile %s: %s", scenario_path, exc)

    # Always provide _time so the {_time} template variable resolves
    state.setdefault("_time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    if not tool_payload:
        return state

    # ── Overlay route fields from SerpAPI search_parameters ──────────────────
    params = tool_payload.get("search_parameters", {})
    if params.get("departure_id"):
        state["origin"] = params["departure_id"]
    if params.get("arrival_id"):
        state["destination"] = params["arrival_id"]
    if params.get("outbound_date"):
        state["start_date"] = params["outbound_date"]
    # ── Build normalised flight list ──────────────────────────────────────────
    _TRAVEL_CLASS_MAP = {1: "economy", 2: "premium_economy", 3: "business", 4: "first"}
    cabin = _TRAVEL_CLASS_MAP.get(int(params.get("travel_class", 1)), "economy")

    flights: list[dict[str, Any]] = []
    for section in ("best_flights", "other_flights"):
        for result in tool_payload.get(section, []):
            legs: list[dict[str, Any]] = result.get("flights", [])
            if not legs:
                continue
            first_leg = legs[0]
            last_leg = legs[-1]
            # For range-merged fixtures each result carries outbound_date
            outbound_date = result.get("outbound_date") or params.get("outbound_date", "")
            flights.append(
                {
                    "flight_number": first_leg.get("flight_number", ""),
                    "carrier": first_leg.get("airline", ""),
                    "carrier_code": _extract_carrier_code(first_leg.get("flight_number", "")),
                    "origin": first_leg.get("departure_airport", {}).get("id", ""),
                    "destination": last_leg.get("arrival_airport", {}).get("id", ""),
                    "departure_time": first_leg.get("departure_airport", {}).get("time", ""),
                    "arrival_time": last_leg.get("arrival_airport", {}).get("time", ""),
                    "outbound_date": outbound_date,
                    "stops": len(result.get("layovers") or []),
                    "duration": result.get("total_duration", 0),
                    "price_usd": result.get("price", 0),
                    "cabin_class": cabin,
                    "booking_token": result.get("booking_token", ""),
                }
            )

    total_count = params.get("_total_flights") or len(
        tool_payload.get("best_flights", []) + tool_payload.get("other_flights", [])
    )

    state[_FLIGHT_CASH_KEY] = flights
    state["total_flights_found"] = total_count
    state["last_cash_search_count"] = total_count
    state["search_params"] = params

    # Mark the session as already initialised so memory.py's load_memory callback
    # skips the target.update(source) branch that would overwrite our route values
    # with the empty strings from the scenario profile.
    state["_itin_initialized"] = True

    return state


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
    """Run an ADK agent asynchronously and return the final response text.

    Retries automatically on 429 RESOURCE_EXHAUSTED with exponential back-off.
    """
    try:
        from google.adk.runners import InMemoryRunner  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("google-adk not installed — returning stub response")
        return f"[NO-ADK] Query: {query}"

    from google.genai import types as genai_types  # type: ignore[import-untyped]

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=query)],
    )

    delay = _RETRY_BASE_DELAY_S
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        runner = InMemoryRunner(agent=root_agent, app_name="adk_quality_lab_eval")
        await runner.session_service.create_session(
            app_name="adk_quality_lab_eval",
            user_id=user_id,
            session_id=session_id,
            state=session_state,
        )
        try:
            last_text = ""
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
            ):
                if hasattr(event, "content") and event.content:
                    for part in event.content.parts or []:
                        if hasattr(part, "text") and part.text:
                            last_text = part.text
            return last_text or "[EMPTY AGENT RESPONSE]"
        except Exception as exc:
            if _is_resource_exhausted(exc) and attempt < _RETRY_MAX_ATTEMPTS:
                logger.warning(
                    "429 RESOURCE_EXHAUSTED (attempt %d/%d) — retrying in %.0fs",
                    attempt, _RETRY_MAX_ATTEMPTS, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * _RETRY_BACKOFF, _RETRY_MAX_DELAY_S)
            else:
                raise


async def _run_multiturn_async(
    root_agent: Any,
    turns: list[str],
    session_state: dict[str, Any],
    user_id: str = "eval-user",
    session_id: str = "eval-session",
) -> list[str]:
    """Run multiple turns in the same ADK session, returning a response per turn."""
    try:
        from google.adk.runners import InMemoryRunner  # type: ignore[import-untyped]
    except ImportError:
        return [f"[NO-ADK] Query: {t}" for t in turns]

    from google.genai import types as genai_types  # type: ignore[import-untyped]

    runner = InMemoryRunner(agent=root_agent, app_name="adk_quality_lab_eval")
    await runner.session_service.create_session(
        app_name="adk_quality_lab_eval",
        user_id=user_id,
        session_id=session_id,
        state=session_state,
    )

    responses: list[str] = []
    for turn_text in turns:
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=turn_text)],
        )
        delay = _RETRY_BASE_DELAY_S
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                last_text = ""
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content,
                ):
                    if hasattr(event, "content") and event.content:
                        for part in event.content.parts or []:
                            if hasattr(part, "text") and part.text:
                                last_text = part.text
                responses.append(last_text or "[EMPTY AGENT RESPONSE]")
                break
            except Exception as exc:
                if _is_resource_exhausted(exc) and attempt < _RETRY_MAX_ATTEMPTS:
                    logger.warning(
                        "429 RESOURCE_EXHAUSTED (turn %d, attempt %d/%d) — retrying in %.0fs",
                        len(responses) + 1, attempt, _RETRY_MAX_ATTEMPTS, delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * _RETRY_BACKOFF, _RETRY_MAX_DELAY_S)
                else:
                    raise

    return responses


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
    variant: str = "baseline",
    use_stub: bool = False,
) -> Any:
    """Build an agent_fn(query, tool_payload) callable for eval runner.

    Each variant corresponds to an isolated, reproducible improvement phase:

    AGENTWILD paper condition mapping:

    ┌──────────────────────┬────────────────────────────────────────────────────┐
    │ VARIANT              │ Paper condition / What is loaded                   │
    ├──────────────────────┼────────────────────────────────────────────────────┤
    │ markdown             │ Cond A — free-form Markdown synthesis, no schema   │
    │ json_block           │ Cond B — JSON code-fence synthesis, no schema      │
    │ baseline             │ Cond C — response_schema (FlightsSelection)        │
    │ arch_fix             │ Cond D — lazy-load get_flight_context, no synth    │
    │ prompt_tuning_v1     │ Cond C + verbatim-citation instruction             │
    │ structured_output    │ alias → prompt_tuning_v1                           │
    │ prompt_tuning_v2     │ Cond C + Optimizer-tuned tool descriptions         │
    └──────────────────────┴────────────────────────────────────────────────────┘

    Judges can replicate any phase independently:
        make eval CASE_SET=both VARIANT=baseline
        make eval CASE_SET=both VARIANT=prompt_tuning_v1
        make eval CASE_SET=both VARIANT=structured_output
        make eval CASE_SET=both VARIANT=arch_fix

    Args:
        example_dir: Path to examples/travel-concierge (auto-detected if None).
        surface: Which sub-agent to target: 'root', 'planning', 'inspiration'.
        variant: Improvement phase to load (see table above).
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

    # Import root agent lazily to avoid import-time side effects.
    # _load_root_agent dispatches on (surface, variant) so each phase is isolated.
    root_agent = _load_root_agent(example_dir, surface, variant)

    def agent_fn(query: str, tool_payload: dict[str, Any] | None = None) -> str:
        session_state = _fixture_to_session_state(tool_payload)
        try:
            return _run_agent_sync(root_agent, query, session_state)
        except Exception as exc:
            logger.error("Agent run failed: %s", exc, exc_info=True)
            return f"[ERROR] {exc}"

    return agent_fn


def build_multiturn_fn(
    example_dir: str | Path | None = None,
    surface: str = "root",
    variant: str = "baseline",
) -> Any:
    """Like build_agent_fn but returns a Callable[[list[str], dict], list[str]].

    Each call runs all turns in a single persistent ADK session so session
    state (including search_results_cash) is preserved across turns.

    Returns:
        Callable[[list[str], dict | None], list[str]]
    """
    if example_dir is None:
        example_dir = Path(__file__).parent.parent.parent / "examples" / "travel-concierge"
    example_dir = Path(example_dir)

    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))

    scenario_key = "TRAVEL_CONCIERGE_SCENARIO"
    if not os.environ.get(scenario_key):
        default_scenario = (
            example_dir / "travel_concierge" / "profiles" / "itinerary_empty_default.json"
        )
        os.environ[scenario_key] = str(default_scenario.resolve())

    root_agent = _load_root_agent(example_dir, surface, variant)

    def multiturn_fn(
        turns: list[str],
        tool_payload: dict[str, Any] | None = None,
    ) -> list[str]:
        session_state = _fixture_to_session_state(tool_payload)
        try:
            # Always create a brand-new event loop so closed loops from previous
            # variant runs don't pollute this call.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    _run_multiturn_async(root_agent, turns, session_state)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        except Exception as exc:
            logger.error("Multi-turn run failed: %s", exc, exc_info=True)
            return [f"[ERROR] {exc}"] * len(turns)

    return multiturn_fn


def _load_root_agent(example_dir: Path, surface: str, variant: str = "baseline") -> Any:
    """Load the appropriate agent object for the requested (surface, variant).

    Variant dispatch for the planning surface:
      baseline          → vanilla vendored planning_agent (upstream prompt)
      prompt_tuning_v1  → vanilla agent with PLANNING_AGENT_INSTR_V1 patched in
      structured_output → planning_agent with JSON schema output enforcement
      prompt_tuning_v2  → planning_agent with Optimizer-tuned tool descriptions
      arch_fix          → planning_agent_v2 (CashFlightSummary architecture)

    For non-planning surfaces, variant is currently ignored — all phases use the
    same root/inspiration agent.  Extended as Optimizer covers more surfaces.

    All variant modules live under:
      examples/travel-concierge/adk_quality_lab_wiring/tuned_prompts/
    so they are never mixed into the vendored travel_concierge package.
    """
    # ── Ensure wiring dir is on sys.path so tuned_prompts imports resolve ──────
    wiring_dir = example_dir / "adk_quality_lab_wiring"
    if str(wiring_dir) not in sys.path:
        sys.path.insert(0, str(wiring_dir))

    try:
        if surface == "planning":
            if variant == "arch_fix":
                from tuned_prompts.planning_agent_v2 import (  # type: ignore[import-untyped]
                    planning_agent_v2 as agent,
                )
                return agent
            elif variant == "prompt_tuning_v1":
                # Patch vanilla planning_agent with Optimizer-tuned instruction v1.
                # planning_prompt_v1.py is written by instruction_tuner.py at
                # the end of the first Optimizer run on the planning surface.
                from travel_concierge.sub_agents.planning.agent import (  # type: ignore[import-untyped]
                    planning_agent,
                )
                from tuned_prompts.planning_prompt_v1 import (  # type: ignore[import-untyped]
                    PLANNING_AGENT_INSTR_V1,
                )
                planning_agent.instruction = PLANNING_AGENT_INSTR_V1
                return planning_agent
            elif variant == "structured_output":
                # structured_output is now an alias for prompt_tuning_v1
                # (planning_agent_structured.py was deleted — it was a duplicate
                # of baseline; prompt_tuning_v1 is the closest equivalent).
                from tuned_prompts.planning_prompt_v1 import (  # type: ignore[import-untyped]
                    planning_agent_v1 as agent,
                )
                return agent
            elif variant == "markdown":
                from tuned_prompts.planning_markdown import (  # type: ignore[import-untyped]
                    planning_agent_markdown as agent,
                )
                return agent
            elif variant == "json_block":
                from tuned_prompts.planning_json_block import (  # type: ignore[import-untyped]
                    planning_agent_json_block as agent,
                )
                return agent
            elif variant == "prompt_tuning_v2":
                # planning_agent_v2b.py adds Optimizer-tuned tool descriptions
                # on top of the structured output variant.
                from tuned_prompts.planning_agent_v2b import (  # type: ignore[import-untyped]
                    planning_agent_v2b as agent,
                )
                return agent
            else:
                # baseline — vanilla planning logic + fixture-backed search_flights tool.
                # The raw vendored agent has no tools on flight_search_agent and hallucinates.
                # planning_baseline.py adds the one tool needed to feed real SerpAPI data
                # through the agent so synthesis faithfulness can be measured.
                # planning_agent instruction (PLANNING_AGENT_INSTR) is identical to upstream.
                from tuned_prompts.planning_baseline import (  # type: ignore[import-untyped]
                    planning_agent_baseline as agent,
                )
                return agent

        elif surface == "root":
            from travel_concierge.agent import root_agent  # type: ignore[import-untyped]
            return root_agent

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
            "Could not import agent for surface=%s variant=%s (is %s in sys.path?): %s",
            surface,
            variant,
            example_dir,
            exc,
        )
        raise
