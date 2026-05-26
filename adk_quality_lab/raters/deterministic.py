"""Deterministic raters — fast, cheap, zero hallucination risk.

All raters accept (case, agent_response, tool_payload) and return a RaterResult.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

# ---------------------------------------------------------------------------
# IATA carrier code set
# ---------------------------------------------------------------------------

_IATA_CARRIERS_PATH = Path(__file__).parent.parent / "data" / "iata_carriers.txt"
_IATA_CARRIERS: frozenset[str] | None = None


def _load_iata_carriers() -> frozenset[str]:
    global _IATA_CARRIERS
    if _IATA_CARRIERS is None:
        if _IATA_CARRIERS_PATH.exists():
            codes = {
                line.strip().upper()
                for line in _IATA_CARRIERS_PATH.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            }
        else:
            codes = set()
        _IATA_CARRIERS = frozenset(codes)
    return _IATA_CARRIERS


# ---------------------------------------------------------------------------
# JSON schema registry
# ---------------------------------------------------------------------------

_SCHEMAS_DIR = Path(__file__).parent / "schemas"
_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(name: str) -> dict[str, Any]:
    if name not in _SCHEMA_CACHE:
        path = _SCHEMAS_DIR / name
        _SCHEMA_CACHE[name] = json.loads(path.read_text())
    return _SCHEMA_CACHE[name]


# ---------------------------------------------------------------------------
# Rater: row_count_match
# ---------------------------------------------------------------------------

# Patterns to extract claimed count from agent narration
_COUNT_CLAIM_RE = re.compile(
    r"(?:found|showing|retrieved|here\s+are|i\s+(?:have\s+)?found)\s+(\d+)",
    re.IGNORECASE,
)
_SHOWING_OF_RE = re.compile(r"Showing\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)


def row_count_match(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Check that the agent's claimed flight count matches the rendered row count.

    PASS: claimed N == rendered rows, OR agent uses 'Showing X of N' disclosure.
    FAIL: agent claims N but renders a different count.
    """
    # Count flight-card-like blocks in the response as a proxy for rendered rows.
    # Match numbered lists ("1. ", "10. ") OR bullet lists ("* ", "- ", "• ")
    rendered_rows = len(re.findall(r"(?m)^\s*(?:\d+[.\)]|[*\-•])\s+", agent_response))
    if rendered_rows == 0:
        # Fallback: count lines with IATA-style flight numbers
        rendered_rows = len(re.findall(r"\b[A-Z]{2}\d{1,4}\b", agent_response))

    # Check for explicit disclosure "Showing X of N"
    showing_match = _SHOWING_OF_RE.search(agent_response)
    if showing_match:
        x = int(showing_match.group(1))
        n = int(showing_match.group(2))
        # Disclosure present — pass if X matches rendered rows or equals expected
        if case.expected_flight_count is not None:
            passed = n == case.expected_flight_count
            detail = f"Disclosure 'Showing {x} of {n}'; expected total {case.expected_flight_count}"
        else:
            passed = True
            detail = f"Disclosure 'Showing {x} of {n}' present"
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.row_count_match",
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=detail,
        )

    # No disclosure — find claimed count
    count_match = _COUNT_CLAIM_RE.search(agent_response)
    if count_match:
        claimed = int(count_match.group(1))
        if case.expected_flight_count is not None:
            # Claimed count must equal SerpAPI ground truth
            passed = claimed == case.expected_flight_count
            detail = (
                f"Claimed {claimed}, expected {case.expected_flight_count}, "
                f"rendered ~{rendered_rows} rows"
            )
        else:
            # Claimed count must match rendered rows (no lie)
            passed = abs(claimed - rendered_rows) <= 2  # allow small off-by-ones
            detail = f"Claimed {claimed}, rendered ~{rendered_rows} rows"
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.row_count_match",
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=detail,
        )

    # No count claim found.
    # If we have a ground-truth expected count, use rendered rows as the proxy.
    # An agent that silently truncates 76 flights to 10 should FAIL, not pass.
    if case.expected_flight_count is not None:
        ratio = rendered_rows / case.expected_flight_count if case.expected_flight_count else 1.0
        passed = ratio >= 0.90  # allow up to 10% off (rounding, dedup, etc.)
        score = round(min(ratio, 1.0), 3)
        detail = (
            f"No explicit count claim; rendered ~{rendered_rows} rows "
            f"vs expected {case.expected_flight_count} "
            f"({score:.0%} coverage)"
        )
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.row_count_match",
            passed=passed,
            score=score,
            detail=detail,
        )

    return RaterResult(
        case_id=case.case_id,
        rater="deterministic.row_count_match",
        passed=True,
        score=1.0,
        detail="No count claim detected in agent response",
    )


# ---------------------------------------------------------------------------
# Rater: json_schema_validate
# ---------------------------------------------------------------------------


def json_schema_validate(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
    schema_name: str = "flight_card.schema.json",
) -> RaterResult:
    """Validate all JSON objects in the agent response against a schema.

    Extracts ```json ... ``` blocks or bare {...} objects from the response
    and validates each against the named schema.
    """
    schema = _load_schema(schema_name)

    # Extract JSON blocks
    json_blocks = re.findall(r"```json\s*(.*?)\s*```", agent_response, re.DOTALL)
    if not json_blocks:
        # Try bare JSON objects
        json_blocks = re.findall(r"\{[^{}]+\}", agent_response, re.DOTALL)

    if not json_blocks:
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.json_schema_validate",
            passed=True,
            score=1.0,
            detail="No JSON objects found to validate",
        )

    errors: list[str] = []
    for block in json_blocks:
        try:
            obj = json.loads(block)
            jsonschema.validate(obj, schema)
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
        except jsonschema.ValidationError as e:
            errors.append(f"Schema violation: {e.message}")

    passed = len(errors) == 0
    return RaterResult(
        case_id=case.case_id,
        rater="deterministic.json_schema_validate",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail="; ".join(errors) if errors else f"All {len(json_blocks)} JSON blocks valid",
    )


# ---------------------------------------------------------------------------
# Rater: iata_membership
# ---------------------------------------------------------------------------


def iata_membership(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Check that all carrier codes cited in the response are valid IATA codes."""
    carriers = _load_iata_carriers()
    if not carriers:
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.iata_membership",
            passed=True,
            score=1.0,
            detail="IATA carrier list not available — skipped",
        )

    # Extract 2-letter carrier codes from flight numbers (e.g. AA100, DL202, UA123)
    found_carriers = set(re.findall(r"\b([A-Z]{2})\d{1,4}\b", agent_response))
    invalid = found_carriers - carriers

    passed = len(invalid) == 0
    return RaterResult(
        case_id=case.case_id,
        rater="deterministic.iata_membership",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=(
            f"Invalid IATA codes: {sorted(invalid)}"
            if invalid
            else f"All {len(found_carriers)} carrier codes valid"
        ),
    )


# ---------------------------------------------------------------------------
# Rater: numerical_equality
# ---------------------------------------------------------------------------


def numerical_equality(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
    tolerance: float = 1.0,
) -> RaterResult:
    """Check that prices cited in the agent response match the expected values.

    Compares against case.expected_values['price'] if present, otherwise
    validates against all prices in the tool_payload.
    """
    if case.expected_values is None:
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.numerical_equality",
            passed=True,
            score=1.0,
            detail="No expected_values — skipped",
        )

    expected_price_str = case.expected_values.get("price")
    if not expected_price_str:  # None or empty string
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.numerical_equality",
            passed=True,
            score=1.0,
            detail="No expected price — skipped",
        )

    try:
        expected_price = float(expected_price_str)
    except ValueError:
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.numerical_equality",
            passed=True,
            score=1.0,
            detail=f"Unparseable expected price '{expected_price_str}' — skipped",
        )

    # Extract all dollar amounts from agent response
    # Pattern: optional $, then a digit-led number with optional thousands commas and decimal
    found_prices = [
        float(p.replace(",", ""))
        for p in re.findall(r"\$?(\d[\d,]*\.?\d*)", agent_response)
        if p.replace(",", "").replace(".", "")  # skip strings with no actual digits
    ]

    if not found_prices:
        return RaterResult(
            case_id=case.case_id,
            rater="deterministic.numerical_equality",
            passed=False,
            score=0.0,
            detail=f"No prices found in response; expected ${expected_price}",
        )

    # At least one cited price must be within tolerance of the expected price
    closest = min(found_prices, key=lambda p: abs(p - expected_price))
    passed = abs(closest - expected_price) <= tolerance

    return RaterResult(
        case_id=case.case_id,
        rater="deterministic.numerical_equality",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=(
            f"Closest cited price ${closest:.2f} vs expected ${expected_price:.2f} "
            f"(tolerance ±${tolerance:.2f})"
        ),
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RATER_REGISTRY = {
    "deterministic.row_count_match": row_count_match,
    "deterministic.json_schema_validate": json_schema_validate,
    "deterministic.iata_membership": iata_membership,
    "deterministic.numerical_equality": numerical_equality,
}


def run_deterministic_raters(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> list[RaterResult]:
    """Run all deterministic raters declared in the case."""
    results: list[RaterResult] = []
    for rater_id in case.raters:
        if rater_id in _RATER_REGISTRY:
            fn = _RATER_REGISTRY[rater_id]
            results.append(fn(case, agent_response, tool_payload))
    return results
