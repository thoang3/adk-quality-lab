# Drop-in replacement for travel_concierge.shared_libraries.firebase
# Used only in the adk-quality-lab eval context — not production.
# Reads SERP_API_KEY from environment; never touches Firebase.

from __future__ import annotations

import os


def get_user_api_key(user_id: str, provider: str) -> str | None:  # noqa: ARG001
    """Return the provider API key from environment — no Firebase call."""
    key_map = {
        "serpapi": "SERP_API_KEY",
        "google_places": "GOOGLE_PLACES_API_KEY",
    }
    env_var = key_map.get(provider.lower(), provider.upper() + "_API_KEY")
    return os.environ.get(env_var)


def get_user_api_key_status(user_id: str, provider: str) -> dict[str, str]:  # noqa: ARG001
    return {"status": "active", "provider": provider}


def update_user_api_key_last_used(user_id: str, provider: str) -> None:  # noqa: ARG001
    pass
