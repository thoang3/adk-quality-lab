#!/usr/bin/env python3
"""Minimal runner that sends one verbal cash-flight query to `root_agent`.

Query:
"Find economy cash flights from SFO to NRT on 2026-08-15"

Variants:
- markdown_table: planning agent renders markdown summary/table
- json_code_block: planning agent renders a JSON code block in markdown
- json_passthrough: planning agent returns structured JSON as-is
"""

import argparse
import asyncio
import json
from pathlib import Path

from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from adk_quality_lab_wiring.playground import agent_variants_minimal_cash_json_code_block as json_code_block_variant
from adk_quality_lab_wiring.playground import agent_variants_minimal_cash_json_passthrough as json_variant
from adk_quality_lab_wiring.playground import agent_variants_minimal_cash_markdown_table as markdown_variant
from adk_quality_lab_wiring import types as shared_types


_PROFILES_DIR = Path(__file__).parent.parent / "profiles"
_DEFAULT_PROFILE = _PROFILES_DIR / "demo_rich_portfolio.json"


def _load_initial_state(profile_path: Path = _DEFAULT_PROFILE) -> dict:
    """Load session state from a profile JSON file (best-effort).

    Tolerates trailing commas (common in hand-edited JSON) by stripping them
    before parsing.
    """
    import re
    from datetime import datetime, timezone

    try:
        raw = profile_path.read_text()
        # Strip trailing commas before } or ] (JSON5-lite)
        fixed = re.sub(r",(\s*[}\]])", r"\1", raw)
        data = json.loads(fixed)
        # Profile files may store state under a "state" key or at the top level
        state = dict(data.get("state", data))
    except Exception:  # noqa: BLE001
        state = {}

    # Always inject _time so the {_time} prompt template variable resolves
    state.setdefault("_time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    return state


QUERY = "Find economy cash flights from SFO to NRT on 2026-07-23"
# Date-range variant (fixtures exist for JFK→CDG July 1–14):
# QUERY = "Find economy cash flights from JFK to CDG from 2026-07-01 to 2026-07-07"
VARIANT_CHOICES = ("markdown_table", "json_code_block", "json_passthrough")
CONFIG_PROFILE_CHOICES = ("default", "deterministic")


def parse_args() -> argparse.Namespace:
    """Parse CLI args for selecting which playground variant to run."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=VARIANT_CHOICES,
        default="markdown_table",
        help="Choose runner target: markdown_table, json_code_block, or json_passthrough",
    )
    parser.add_argument(
        "--config-profile",
        choices=CONFIG_PROFILE_CHOICES,
        default="default",
        help="Choose generation profile: default or deterministic",
    )
    return parser.parse_args()


def apply_config_profile(variant: str, config_profile: str) -> None:
    """Apply a generation config profile to the selected planning variant."""
    if variant == "json_passthrough":
        if config_profile == "deterministic":
            json_variant.planning_agent_minimal_cash.generate_content_config = (
                shared_types.json_deterministic_config
            )
        else:
            json_variant.planning_agent_minimal_cash.generate_content_config = (
                shared_types.json_default_config
            )
        return

    if variant == "json_code_block":
        if config_profile == "deterministic":
            json_code_block_variant.planning_agent_minimal_cash.generate_content_config = (
                shared_types.markdown_deterministic_config
            )
        else:
            json_code_block_variant.planning_agent_minimal_cash.generate_content_config = (
                shared_types.markdown_default_config
            )
        return

    if config_profile == "deterministic":
        markdown_variant.planning_agent_minimal_cash.generate_content_config = (
            shared_types.markdown_deterministic_config
        )
    else:
        markdown_variant.planning_agent_minimal_cash.generate_content_config = (
            shared_types.markdown_default_config
        )


def resolve_variant(variant: str):
    """Resolve selected variant to `(agent, app_name)` tuple."""
    if variant == "json_passthrough":
        return (
            json_variant.root_agent_minimal_cash,
            "playground_root_agent_minimal_cash_passthrough",
        )
    if variant == "json_code_block":
        return (
            json_code_block_variant.root_agent_minimal_cash,
            "playground_root_agent_minimal_cash_json_code_block",
        )
    return (
        markdown_variant.root_agent_minimal_cash,
        "playground_root_agent_minimal_cash",
    )


async def main(variant: str, config_profile: str) -> None:
    apply_config_profile(variant, config_profile)
    root_agent, app_name = resolve_variant(variant)
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)

    initial_state = _load_initial_state()
    session = await runner.session_service.create_session(
        app_name=app_name,
        user_id="playground_user",
        state=initial_state or None,
    )

    message = genai_types.Content(role="user", parts=[genai_types.Part(text=QUERY)])

    print(f"variant: {variant}")
    print(f"config_profile: {config_profile}")
    print(f"query: {QUERY}\n")
    print("response:\n" + "-" * 60)

    passthrough_text_parts: list[str] = []

    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=message,
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text:
                if variant == "json_passthrough":
                    passthrough_text_parts.append(part.text)
                else:
                    print(part.text, end="", flush=True)

    if variant == "json_passthrough":
        payload_text = "".join(passthrough_text_parts).strip()
        try:
            payload = json.loads(payload_text)
            # flights = payload.get("flights", []) if isinstance(payload, dict) else []
            print(json.dumps(payload, indent=2), end="", flush=True)
        except json.JSONDecodeError:
            print(payload_text, end="", flush=True)

    print("\n" + "-" * 60)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.variant, args.config_profile))
