"""CLI: print results from the local runs/runs.jsonl file.

Usage:
    python -m adk_quality_lab.cli.show              # last run
    python -m adk_quality_lab.cli.show --last 3     # last 3 runs
    python -m adk_quality_lab.cli.show --run-id <id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_RUNS_FILE = Path(__file__).parent.parent.parent / "runs" / "runs.jsonl"


def _load_runs(n: int | None = None, run_id: str | None = None) -> list[dict]:
    if not _RUNS_FILE.exists():
        return []
    lines = [l for l in _RUNS_FILE.read_text().splitlines() if l.strip()]
    runs = [json.loads(l) for l in lines]
    if run_id:
        runs = [r for r in runs if r.get("run_id", "").startswith(run_id)]
    if n:
        runs = runs[-n:]
    return runs


def _print_run(run: dict) -> None:
    print(f"\n{'='*70}")
    print(f"Run ID:    {run['run_id']}")
    print(f"Variant:   {run.get('variant', '?')}")
    print(f"Aggregate: {run.get('aggregate_score', 0):.3f}   Cases: {len(run.get('cases', []))}")
    print(f"{'='*70}")

    cases = run.get("cases", [])
    if not cases:
        print("  (no case detail stored)")
        return

    header = f"  {'CASE':<14} {'RATER':<35} {'SCORE':>6}  {'P':>1}  DETAIL"
    print(header)
    print("  " + "-" * 68)
    for r in cases:
        case_id = r.get("case_id", "?")
        rater = r.get("rater", "?").replace("deterministic.", "")
        score = r.get("score", 0)
        passed = "✓" if r.get("passed") else "✗"
        detail = (r.get("detail") or "")[:48]
        print(f"  {case_id:<14} {rater:<35} {score:>6.3f}  {passed}  {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show local eval run results")
    parser.add_argument("--last", type=int, default=1, help="Show last N runs (default: 1)")
    parser.add_argument("--run-id", default=None, help="Filter by run ID prefix")
    parser.add_argument("--all", action="store_true", help="Show all runs")
    args = parser.parse_args()

    n = None if args.all else args.last
    runs = _load_runs(n=n, run_id=args.run_id)

    if not runs:
        print(f"No runs found in {_RUNS_FILE}")
        return

    for run in runs:
        _print_run(run)


if __name__ == "__main__":
    main()
