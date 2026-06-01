# Copyright 2025 Google LLC
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

"""Profile-related tools for accessing user loyalty program information."""

import logging
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


def get_current_profile(tool_context: ToolContext) -> dict[str, Any]:
    """Get current user profile from session state.

    This tool reads the user's complete profile directly from the current
    session state, ensuring you always get the most up-to-date values even if the
    user has updated their profile mid-conversation.

    The profile includes:
    - available_awards: Loyalty program point balances and expiration dates
    - personal_valuations: Custom valuations for each program (cents per point)
    - preferences: Travel preferences (cabin class, airlines, etc.)
    - Other profile fields as configured by the user

    IMPORTANT: Profile data can change during conversations when users update
    their wallet or preferences. ALWAYS call this tool to get fresh data - do not
    rely on profile information mentioned earlier in the conversation or in the
    user_profile template.

    Args:
        tool_context: The ADK tool context containing session state.

    Returns:
        The complete user_profile dictionary from session state. Example:
        {
            "available_awards": {
                "aeroplan": {
                    "points_balance": 124200,
                    "expiration_date": "never"
                },
                "alaska_miles": {
                    "points_balance": 151000,
                    "expiration_date": "2026-12-31"
                }
            },
            "personal_valuations": {
                "aeroplan": 3.0,
                "alaska_miles": 2.5
            },
            "preferences": {
                "preferred_cabin": "business",
                "max_stops": 1
            }
        }
        Returns empty dict if no user profile found in session.
    """
    # Defensive: Check if tool_context has valid state before accessing it
    state = getattr(tool_context, "state", None)
    if not state or not hasattr(state, "get"):
        logger.warning(
            "🔍 get_current_profile: No valid session state found in tool_context"
        )
        return {}

    user_profile = state.get("user_profile", {})

    if not user_profile:
        logger.info("🔍 get_current_profile: No user_profile found in session state")
        return {}

    logger.debug(
        f"🔍 get_current_profile: Returning profile with {len(user_profile.get('available_awards', {}))} programs, "
        f"{len(user_profile.get('personal_valuations', {}))} valuations"
    )

    return user_profile
