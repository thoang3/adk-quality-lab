"""Shared helpers for integration tests.

Integration tests are opt-in — they make real API calls and should never run
in CI.  Use ``require_serp_key`` as a pytest fixture or decorator to
automatically skip when the key is absent or the opt-in env var is not set.
"""

from __future__ import annotations

import os

import pytest


def require_serp_key() -> str:
    """Return the SERP_API_KEY or skip the test.

    Skips if:
    - ``RUN_HOTEL_EXPLORATION_TESTS`` is not set to ``"1"``
    - ``SERP_API_KEY`` is absent or empty
    """
    if os.environ.get("RUN_HOTEL_EXPLORATION_TESTS") != "1":
        pytest.skip("Set RUN_HOTEL_EXPLORATION_TESTS=1 to run integration tests")
    key = os.environ.get("SERP_API_KEY", "").strip()
    if not key:
        pytest.skip("SERP_API_KEY not set")
    return key
