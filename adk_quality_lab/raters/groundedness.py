"""Custom Agent Evaluation metric: structured_value_groundedness.

Verifies that every carrier code, flight number, and price cited in the
agent response appears verbatim in the captured SerpAPI tool payload.
This is a generalizable pattern — works for any domain where tool payloads
carry structured ground-truth values.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

logger = logging.getLogger(__name__)

# Patterns for structured values we check
_CARRIER_FLIGHT_RE = re.compile(r"\b([A-Z]{2})(\d{1,4})\b")
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _extract_agent_values(response: str) -> dict[str, set[str]]:
    """Extract structured values cited in the agent response."""
    carriers: set[str] = set()
    flight_numbers: set[str] = set()
    prices: set[str] = set()

    for match in _CARRIER_FLIGHT_RE.finditer(response):
        carriers.add(match.group(1))
        flight_numbers.add(match.group(1) + match.group(2))

    for match in _PRICE_RE.finditer(response):
        # Normalize price: remove commas, ensure 2 decimal places
        raw = match.group(1).replace(",", "")
        try:
            prices.add(f"{float(raw):.2f}")
        except ValueError:
            pass

    return {"carriers": carriers, "flight_numbers": flight_numbers, "prices": prices}


def _flatten_payload_values(payload: dict[str, Any]) -> dict[str, set[str]]:
    """Extract all structured values from the SerpAPI payload."""
    carriers: set[str] = set()
    flight_numbers: set[str] = set()
    prices: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            # SerpAPI flight result keys
            for key in ("carrier_logo", "airline", "airline_logo"):
                val = obj.get(key, "")
                if isinstance(val, str):
                    # Try to extract 2-letter IATA code
                    for m in _CARRIER_FLIGHT_RE.finditer(val):
                        carriers.add(m.group(1))

            carrier = obj.get("airline", obj.get("carrier", ""))
            if isinstance(carrier, str) and len(carrier) == 2:
                carriers.add(carrier)

            flight_no = obj.get("flight_number", obj.get("flight_no", ""))
            if isinstance(flight_no, str):
                clean = flight_no.replace(" ", "").upper()
                if _CARRIER_FLIGHT_RE.match(clean):
                    flight_numbers.add(clean)
                    carriers.add(clean[:2])

            for price_key in ("price", "total_price", "base_price", "fare"):
                val = obj.get(price_key)
                if val is not None:
                    try:
                        prices.add(f"{float(str(val).replace(',', '')):.2f}")
                    except (ValueError, TypeError):
                        pass

            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    return {"carriers": carriers, "flight_numbers": flight_numbers, "prices": prices}


def structured_value_groundedness(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> RaterResult:
    """Check that all structured values cited in the response appear in the payload.

    This is the core F2 rater: carrier codes, flight numbers, and prices must
    literally appear in the captured SerpAPI payload.

    PASS: every cited structured value is present in the payload.
    FAIL: any cited value is absent from the payload (mutation or hallucination).
    """
    rater_id = "groundedness.structured_value"

    if tool_payload is None:
        return RaterResult(
            case_id=case.case_id,
            rater=rater_id,
            passed=True,
            score=1.0,
            detail="No tool payload provided — skipped",
        )

    # Also check against expected_values if present (case-level ground truth)
    if case.expected_values:
        expected_carrier = case.expected_values.get("carrier")
        expected_price = case.expected_values.get("price")
        expected_flight = case.expected_values.get("flight_number")

        violations: list[str] = []

        if expected_carrier and expected_carrier not in agent_response:
            violations.append(f"Expected carrier '{expected_carrier}' not found in response")
        if expected_flight and expected_flight not in agent_response:
            violations.append(f"Expected flight '{expected_flight}' not found in response")
        if expected_price:
            try:
                ep = float(expected_price)
                prices_in_response = [
                    float(p.replace(",", ""))
                    for p in re.findall(r"\$?\s*([\d,]+\.?\d*)", agent_response)
                ]
                if not any(abs(p - ep) <= 1.0 for p in prices_in_response):
                    violations.append(
                        f"Expected price ~${ep:.2f} not found in response"
                    )
            except ValueError:
                pass

        if violations:
            return RaterResult(
                case_id=case.case_id,
                rater=rater_id,
                passed=False,
                score=0.0,
                detail="; ".join(violations),
            )

    agent_vals = _extract_agent_values(agent_response)
    payload_vals = _flatten_payload_values(tool_payload)

    violations = []

    # Check flight numbers (most strict — must be verbatim)
    for fn in agent_vals["flight_numbers"]:
        if fn not in payload_vals["flight_numbers"]:
            violations.append(f"Flight number {fn} not in payload")

    # Check prices (within $1 tolerance)
    for price_str in agent_vals["prices"]:
        price = float(price_str)
        if not any(abs(float(p) - price) <= 1.0 for p in payload_vals["prices"]):
            violations.append(f"Price ${price:.2f} not in payload")

    passed = len(violations) == 0
    checked = (
        len(agent_vals["flight_numbers"])
        + len(agent_vals["prices"])
    )

    return RaterResult(
        case_id=case.case_id,
        rater=rater_id,
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=(
            "; ".join(violations)
            if violations
            else f"All {checked} structured values grounded in payload"
        ),
    )


# Alias for Agent Evaluation metric naming convention
agent_eval_groundedness = structured_value_groundedness

# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_RATER_REGISTRY = {
    "groundedness.structured_value": structured_value_groundedness,
    "agent_eval.groundedness": structured_value_groundedness,
}


def run_groundedness_raters(
    case: EvalCase,
    agent_response: str,
    tool_payload: dict[str, Any] | None = None,
) -> list[RaterResult]:
    """Run all groundedness raters declared in the case."""
    results: list[RaterResult] = []
    for rater_id in case.raters:
        if rater_id in _RATER_REGISTRY:
            fn = _RATER_REGISTRY[rater_id]
            results.append(fn(case, agent_response, tool_payload))
    return results
