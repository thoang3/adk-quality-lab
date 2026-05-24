# Drop-in replacement for travel_concierge.shared_libraries.firebase
# Used only in the adk-quality-lab eval context — not production.
# Reads SERP_API_KEY from environment; never touches Firebase.

from __future__ import annotations

import os


def get_user_api_key(user_id: str, provider: str) -> str | None:  # noqa: ARG001
    """Return the SERP_API_KEY from env — no Firebase call."""
    return os.environ.get("SERP_API_KEY")


def get_user_api_key_status(user_id: str, provider: str) -> dict[str, str]:  # noqa: ARG001
    return {"status": "active", "provider": provider}


def update_user_api_key_last_used(user_id: str, provider: str) -> None:  # noqa: ARG001
    pass
