"""ADK before/after agent callbacks for capturing tool-call payloads.

These callbacks are the source of truth for F2 groundedness rater:
every tool response is captured verbatim and written to Firestore so the
rater can check that what the agent cited actually came from the tool.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Thread-local / run-scoped storage for captured tool calls
# Key: case_id → list of tool_call dicts
_tool_call_buffer: dict[str, list[dict[str, Any]]] = {}


def reset_buffer(case_id: str) -> None:
    """Clear the capture buffer for a new eval case run."""
    _tool_call_buffer[case_id] = []


def get_captured_payloads(case_id: str) -> list[dict[str, Any]]:
    """Retrieve all captured tool payloads for a case."""
    return list(_tool_call_buffer.get(case_id, []))


def get_merged_payload(case_id: str) -> dict[str, Any]:
    """Merge all captured tool payloads into one dict (last-write wins on key conflicts)."""
    merged: dict[str, Any] = {}
    for payload in get_captured_payloads(case_id):
        merged.update(payload)
    return merged


# ---------------------------------------------------------------------------
# ADK callback hooks
# ---------------------------------------------------------------------------


def before_agent_callback(
    callback_context: Any,  # google.adk.agents.CallbackContext
) -> None:
    """Called before the agent processes each turn.

    Used to initialise per-case state such as tool call counters.
    """
    case_id = _get_case_id(callback_context)
    if case_id:
        reset_buffer(case_id)
        logger.debug("before_agent_callback: reset buffer for case %s", case_id)


def after_agent_callback(
    callback_context: Any,  # google.adk.agents.CallbackContext
) -> None:
    """Called after the agent finishes processing a turn.

    Captures the final tool-call history from session state and optionally
    persists to Firestore.
    """
    case_id = _get_case_id(callback_context)
    if not case_id:
        return

    payloads = get_captured_payloads(case_id)
    logger.debug(
        "after_agent_callback: case %s captured %d tool payloads",
        case_id,
        len(payloads),
    )

    # Persist to Firestore if configured
    try:
        from adk_quality_lab.observability.firestore_writer import (
            write_tool_payloads,  # noqa: PLC0415
        )

        write_tool_payloads(case_id, payloads)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firestore write skipped: %s", exc)


def capture_tool_response(
    case_id: str,
    tool_name: str,
    tool_response: Any,
) -> None:
    """Explicitly capture a tool response (called from tool wrappers).

    This is the primary capture path when ADK callbacks cannot be hooked
    directly into the tool execution lifecycle.
    """
    if case_id not in _tool_call_buffer:
        _tool_call_buffer[case_id] = []

    entry: dict[str, Any] = {
        "tool_name": tool_name,
        "response": tool_response,
    }
    _tool_call_buffer[case_id].append(entry)
    logger.debug("captured tool response for case %s from %s", case_id, tool_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_case_id(callback_context: Any) -> str | None:
    """Extract the current case_id from callback context session state."""
    try:
        return str(callback_context.state.get("_aql_case_id", ""))
    except Exception:  # noqa: BLE001
        return None
