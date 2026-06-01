#!/usr/bin/env python3
"""Run all cash-query variant/config combinations and print a compact summary."""

import argparse
import asyncio
import time
from collections.abc import Sequence

from adk_quality_lab_wiring.playground import root_agent_cash_query as runner


def parse_args() -> argparse.Namespace:
    """Parse CLI args for matrix execution."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query",
        default=None,
        help=(
            "Optional natural-language query override. "
            "If omitted, uses QUERY from root_agent_cash_query.py."
        ),
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(runner.VARIANT_CHOICES),
        choices=list(runner.VARIANT_CHOICES),
        help="Subset of variants to run.",
    )
    parser.add_argument(
        "--config-profiles",
        nargs="+",
        default=list(runner.CONFIG_PROFILE_CHOICES),
        choices=list(runner.CONFIG_PROFILE_CHOICES),
        help="Subset of config profiles to run.",
    )
    return parser.parse_args()


async def run_one(variant: str, config_profile: str) -> tuple[bool, float, str]:
    """Run one combination and return (ok, elapsed_seconds, error_message)."""
    started = time.perf_counter()
    try:
        await runner.main(variant, config_profile)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - started
        return False, elapsed, f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    return True, elapsed, ""


def print_summary(
    results: Sequence[tuple[str, str, bool, float, str]],
    query: str,
) -> None:
    """Print compact run summary table."""
    print("\n" + "=" * 78)
    print("MATRIX SUMMARY")
    print(f"query: {query}")
    print("-" * 78)
    print(f"{'variant':<18} {'profile':<14} {'status':<8} {'seconds':>8}  note")
    print("-" * 78)

    for variant, profile, ok, elapsed, error in results:
        status = "PASS" if ok else "FAIL"
        note = "" if ok else error
        print(f"{variant:<18} {profile:<14} {status:<8} {elapsed:>8.2f}  {note}")

    total = len(results)
    passed = sum(1 for _, _, ok, _, _ in results if ok)
    print("-" * 78)
    print(f"passed: {passed}/{total}")


async def main() -> int:
    """Execute matrix runs and return shell-compatible exit code."""
    args = parse_args()

    if args.query:
        runner.QUERY = args.query

    print("Running matrix:")
    print(f"  variants: {', '.join(args.variants)}")
    print(f"  profiles: {', '.join(args.config_profiles)}")

    results: list[tuple[str, str, bool, float, str]] = []

    for variant in args.variants:
        for config_profile in args.config_profiles:
            print("\n" + "=" * 78)
            print(f"RUN variant={variant} profile={config_profile}")
            ok, elapsed, error = await run_one(variant, config_profile)
            results.append((variant, config_profile, ok, elapsed, error))

    print_summary(results, runner.QUERY)
    all_ok = all(ok for _, _, ok, _, _ in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
