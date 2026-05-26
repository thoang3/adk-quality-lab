"""Run all variants on a single case and print raw agent responses.

Usage:
    uv run python scripts/compare_variants.py [case_id]
"""
import sys
import logging
from pathlib import Path

# Suppress INFO noise from ADK / httpx
logging.disable(logging.CRITICAL)

sys.path.insert(0, ".")
sys.path.insert(0, "examples/travel-concierge")

from adk_quality_lab.datasets.loader import load_all_cases  # noqa: E402
from adk_quality_lab.datasets.schema import EvalCase  # noqa: E402
from adk_quality_lab.runner import load_fixture  # noqa: E402
from adk_quality_lab.tools.agent_runner import build_agent_fn, build_multiturn_fn  # noqa: E402

# Load all known datasets including tail_flights
_DATASETS_DIR = Path(__file__).parent.parent / "datasets"

def _load_all() -> list[EvalCase]:
    import json
    cases = list(load_all_cases())
    for extra in ["tail_flights.jsonl"]:
        p = _DATASETS_DIR / extra
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line:
                    cases.append(EvalCase.model_validate(json.loads(line)))
    return cases

CASE_ID = sys.argv[1] if len(sys.argv) > 1 else "f1_001"
VARIANTS = ["baseline", "markdown", "json_block", "arch_fix"]

# Optional extra turns for multi-turn testing.
# Pass via --turns flag: --turns "follow up 1" "follow up 2"
# Or set COMPARE_TURNS env var as newline-separated turns.
import os as _os
_turns_env = _os.environ.get("COMPARE_TURNS", "")
EXTRA_TURNS: list[str] = (
    sys.argv[sys.argv.index("--turns") + 1:]
    if "--turns" in sys.argv
    else ([t for t in _turns_env.splitlines() if t.strip()] if _turns_env else [])
)

all_cases = _load_all()
case = next((c for c in all_cases if c.case_id == CASE_ID), None)
if case is None:
    print(f"Case {CASE_ID!r} not found. Available: {[c.case_id for c in all_cases[:5]]}")
    sys.exit(1)

print(f"Case     : {case.case_id}")
print(f"Query    : {case.query}")
print(f"Expected : {case.expected_flight_count} flights")

tool_payload = load_fixture(case.fixture_hash)
if tool_payload is None:
    print(f"[ERROR] Fixture not found for hash {case.fixture_hash}")
    sys.exit(1)

# Augment query with date/route from fixture so agents don't ask for clarification
# (same data the session state already has — just makes it explicit in the query)
from adk_quality_lab.tools.agent_runner import _fixture_to_session_state
state = _fixture_to_session_state(tool_payload)
origin = state.get("origin", "")
destination = state.get("destination", "")
start_date = state.get("start_date", "")
cabin = case.cabin or "economy"
if origin and destination and start_date:
    augmented_query = f"{case.query} on {start_date} (route: {origin}-{destination}, {cabin})"
else:
    augmented_query = case.query
print(f"Augmented: {augmented_query}")

for variant in VARIANTS:
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  VARIANT: {variant}")
    print(sep)
    # Purge cached agent/tuned_prompts modules so each variant gets a fresh import.
    import importlib
    stale = [m for m in sys.modules if m.startswith(("tuned_prompts", "travel_concierge"))]
    for m in stale:
        del sys.modules[m]
    try:
        if EXTRA_TURNS:
            # Multi-turn mode: run augmented_query as turn 1, then each extra turn
            all_turns = [augmented_query] + EXTRA_TURNS
            mt_fn = build_multiturn_fn(surface="planning", variant=variant)
            responses = mt_fn(all_turns, tool_payload)
            for i, (turn, resp) in enumerate(zip(all_turns, responses), 1):
                print(f"\n--- Turn {i}: {turn!r} ---")
                print(resp)
        else:
            agent_fn = build_agent_fn(surface="planning", variant=variant)
            response = agent_fn(augmented_query, tool_payload)
            print(response)
    except Exception as exc:
        import traceback
        print(f"[ERROR] {exc}")
        traceback.print_exc()
