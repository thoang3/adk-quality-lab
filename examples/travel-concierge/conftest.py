"""conftest.py for examples/travel-concierge.

Patches travel_concierge.shared_libraries.firebase with the no-op stub
so eval runs never touch a live Firebase instance.
"""

import sys
from pathlib import Path

# Ensure the wiring directory is importable
_wiring_dir = Path(__file__).parent / "adk_quality_lab_wiring"
sys.path.insert(0, str(_wiring_dir.parent))

# Patch firebase before any travel_concierge imports occur
import adk_quality_lab_wiring.firebase_stub as _stub  # noqa: E402

sys.modules["travel_concierge.shared_libraries.firebase"] = _stub  # type: ignore[assignment]
