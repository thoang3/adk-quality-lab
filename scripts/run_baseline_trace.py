"""Run a single query through the planning surface with detailed runtime traces.

This script is intended for debugging/validation when you want to verify:
  query -> root agent -> planning agent -> sub-agent/tool calls -> final text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any


logger = logging.getLogger("run_baseline_trace")


def _patch_firebase_stub(example_dir: Path) -> None:
    wiring = example_dir / "adk_quality_lab_wiring"
    if str(wiring.parent) not in sys.path:
        sys.path.insert(0, str(wiring.parent))
    try:
        import adk_quality_lab_wiring.firebase_stub as stub  # noqa: PLC0415

        sys.modules["travel_concierge.shared_libraries.firebase"] = stub  # type: ignore[assignment]
    except ImportError:
        logger.debug("No firebase stub patch applied")


def _log_agent_tree(agent: Any, indent: int = 0) -> None:
    prefix = "  " * indent
    name = getattr(agent, "name", "<unnamed>")
    description = getattr(agent, "description", "")
    logger.info("%sAgent: %s", prefix, name)
    if description:
        logger.info("%s  Description: %s", prefix, str(description).strip())

    tools = getattr(agent, "tools", []) or []
    for tool in tools:
        tool_cls = type(tool).__name__
        if hasattr(tool, "agent") and getattr(tool, "agent") is not None:
            sub = getattr(tool, "agent")
            sub_name = getattr(sub, "name", "<unnamed-sub-agent>")
            logger.info("%s  Tool[%s]: AgentTool -> %s", prefix, tool_cls, sub_name)
            _log_agent_tree(sub, indent + 2)
        elif hasattr(tool, "func") and getattr(tool, "func") is not None:
            func = getattr(tool, "func")
            func_name = getattr(func, "__name__", repr(func))
            logger.info("%s  Tool[%s]: FunctionTool -> %s", prefix, tool_cls, func_name)
        elif hasattr(tool, "name"):
            logger.info("%s  Tool[%s]: %s", prefix, tool_cls, getattr(tool, "name"))
        else:
            logger.info("%s  Tool[%s]", prefix, tool_cls)


def _log_root_planning_wiring(root_agent: Any) -> None:
    planning_nodes = [
        agent
        for agent in (getattr(root_agent, "sub_agents", []) or [])
        if getattr(agent, "name", "") == "planning_agent"
    ]
    if not planning_nodes:
        logger.warning("No planning_agent found under root_agent sub_agents")
        return

    try:
        from tuned_prompts.planning_agent_baseline import planning_agent_baseline  # noqa: PLC0415

        is_baseline_identity = planning_nodes[0] is planning_agent_baseline
        logger.info(
            "Root planning wiring check: planning_agent_baseline_identity=%s",
            is_baseline_identity,
        )
        logger.info(
            "Root planning wiring target symbol: tuned_prompts.planning_agent_baseline.planning_agent_baseline",
        )
    except ImportError:
        logger.warning("Could not import tuned baseline symbol for wiring identity check")


async def _run_with_event_trace(
    root_agent: Any,
    query: str,
    session_state: dict[str, Any],
) -> str:
    from google.adk.runners import InMemoryRunner  # type: ignore[import-untyped]
    from google.genai import types as genai_types  # type: ignore[import-untyped]

    runner = InMemoryRunner(agent=root_agent, app_name="adk_quality_lab_trace")
    user_id = "trace-user"
    session_id = "trace-session"

    await runner.session_service.create_session(
        app_name="adk_quality_lab_trace",
        user_id=user_id,
        session_id=session_id,
        state=session_state,
    )

    content = genai_types.Content(role="user", parts=[genai_types.Part(text=query)])

    text_parts: list[str] = []
    saw_flight_search_response = False
    logger.info("--- Runtime Event Trace Start ---")
    event_idx = 0
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        event_idx += 1
        speaker = (
            getattr(event, "author", None)
            or getattr(event, "agent_name", None)
            or "<unknown-speaker>"
        )
        logger.info(
            "Event[%d] speaker=%s type=%s",
            event_idx,
            speaker,
            type(event).__name__,
        )
        if hasattr(event, "content") and event.content:
            parts = getattr(event.content, "parts", []) or []
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    logger.info("  [%s] text: %s", speaker, text[:300].replace("\n", " "))
                    if saw_flight_search_response and speaker == "planning_agent":
                        logger.info("  [AFTER planning_agent] text passed to user:\n%s", text)
                    text_parts.append(text)

                fn_call = getattr(part, "function_call", None)
                if fn_call:
                    fn_name = getattr(fn_call, "name", "<unknown>")
                    fn_args = getattr(fn_call, "args", None)
                    logger.info("  [%s] function_call: %s args=%s", speaker, fn_name, fn_args)

                fn_resp = getattr(part, "function_response", None)
                if fn_resp:
                    fn_name = getattr(fn_resp, "name", "<unknown>")
                    response = getattr(fn_resp, "response", None)
                    logger.info(
                        "  [%s] function_response: %s response=%s",
                        speaker,
                        fn_name,
                        str(response)[:500],
                    )
                    if fn_name == "flight_search_agent":
                        saw_flight_search_response = True
                        try:
                            response_json = json.dumps(response, indent=2, ensure_ascii=False)
                        except TypeError:
                            response_json = str(response)
                        logger.info(
                            "  [BEFORE planning_agent] flight_search_agent returned:\n%s",
                            response_json,
                        )
    logger.info("--- Runtime Event Trace End ---")
    return "\n\n".join(text_parts) if text_parts else "[EMPTY AGENT RESPONSE]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace one planning query with verbose wiring/runtime logs")
    parser.add_argument("--query", required=True, help="User query to run")
    parser.add_argument("--variant", default="baseline", choices=["baseline", "arch_fix"])
    parser.add_argument("--surface", default="planning", choices=["planning", "root", "inspiration"])
    parser.add_argument("--example-dir", default="examples/travel-concierge")
    parser.add_argument("--fixture-hash", default=None, help="Optional fixture hash to preload as tool payload")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument(
        "--log-file",
        default="backend.log",
        help="Path to write detailed trace logs (default: backend.log)",
    )
    args = parser.parse_args()

    log_path = Path(args.log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        ],
    )
    logger.info("Writing detailed trace logs to %s", log_path)

    example_dir = Path(args.example_dir).resolve()
    if str(example_dir) not in sys.path:
        sys.path.insert(0, str(example_dir))

    _patch_firebase_stub(example_dir)

    scenario_key = "TRAVEL_CONCIERGE_SCENARIO"
    if not os.environ.get(scenario_key):
        default_scenario = example_dir / "travel_concierge" / "profiles" / "itinerary_empty_default.json"
        os.environ[scenario_key] = str(default_scenario.resolve())

    from adk_quality_lab.runner import load_fixture  # noqa: PLC0415
    from adk_quality_lab.tools import agent_runner  # noqa: PLC0415

    payload = load_fixture(args.fixture_hash) if args.fixture_hash else None

    root_agent = agent_runner._load_root_agent(example_dir, args.surface, args.variant)
    logger.info("Loaded root agent for surface=%s variant=%s", args.surface, args.variant)
    _log_agent_tree(root_agent)
    if args.surface == "root":
        _log_root_planning_wiring(root_agent)

    session_state = agent_runner._fixture_to_session_state(payload)
    logger.info("Session state keys: %s", sorted(session_state.keys()))

    final_text = asyncio.run(_run_with_event_trace(root_agent, args.query, session_state))
    logger.info("Final agent response length: %d characters", len(final_text))
    print("\n=== FINAL AGENT RESPONSE ===\n")
    print(final_text)


if __name__ == "__main__":
    main()
