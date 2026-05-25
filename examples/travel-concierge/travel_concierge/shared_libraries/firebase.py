# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Firebase stub for the eval harness.

In the eval context there is no Firebase instance. API keys are resolved from
environment variables instead (SERP_API_KEY). All write operations are no-ops.
"""

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


def get_user_api_key_status(user_id: str, provider: str) -> dict:  # noqa: ARG001
    return {"status": "active", "provider": provider}


def update_user_api_key_last_used(user_id: str, provider: str) -> None:  # noqa: ARG001
    pass
