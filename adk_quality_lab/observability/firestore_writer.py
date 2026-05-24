"""Firestore writer for persisting eval run data.

Run structure in Firestore:
  adk_quality_lab/
    runs/{run_id}/
      cases/{case_id}   ← RaterResult + tool_payloads
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_COLLECTION = "adk_quality_lab"
_firestore_client: Any = None


def _get_client() -> Any:
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore  # type: ignore[import-untyped]

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-quality-lab-tung")
        _firestore_client = firestore.Client(project=project)
    return _firestore_client


def write_tool_payloads(
    case_id: str,
    payloads: list[dict[str, Any]],
    run_id: str = "latest",
) -> None:
    """Persist captured tool payloads to Firestore.

    Path: adk_quality_lab/runs/{run_id}/cases/{case_id}
    """
    try:
        client = _get_client()
        doc_ref = (
            client.collection(_COLLECTION)
            .document("runs")
            .collection(run_id)
            .document(case_id)
        )
        doc_ref.set({"tool_payloads": payloads}, merge=True)
        logger.debug("Wrote %d payloads for case %s to Firestore", len(payloads), case_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firestore write failed for case %s: %s", case_id, exc)


def write_run_result(
    run_id: str,
    run_data: dict[str, Any],
) -> None:
    """Persist a full RunResult to Firestore (and downstream to BigQuery)."""
    try:
        client = _get_client()
        doc_ref = (
            client.collection(_COLLECTION)
            .document("runs")
            .collection("meta")
            .document(run_id)
        )
        doc_ref.set(run_data)
        logger.info("Wrote run %s to Firestore", run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firestore run write failed for %s: %s", run_id, exc)


def write_rater_result(
    run_id: str,
    case_id: str,
    rater_data: dict[str, Any],
) -> None:
    """Persist a single RaterResult to Firestore."""
    try:
        client = _get_client()
        doc_ref = (
            client.collection(_COLLECTION)
            .document("runs")
            .collection(run_id)
            .document(case_id)
        )
        doc_ref.set({"rater_results": rater_data}, merge=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firestore rater write failed: %s", exc)
