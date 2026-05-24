"""Failure cluster analysis using sentence-transformers + HDBSCAN.

Groups failing eval cases by semantic similarity of their failure signatures,
so the proposer prompt can focus on the most representative cluster exemplars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from adk_quality_lab.datasets.schema import EvalCase, RaterResult

logger = logging.getLogger(__name__)


@dataclass
class FailureCluster:
    """A cluster of semantically similar failing cases."""

    cluster_id: int
    exemplars: list[EvalCase]
    rater_results: list[RaterResult]
    failure_mode: str = ""
    size: int = 0

    def exemplar_texts(self, n: int = 3) -> list[str]:
        """Return the top-n exemplar query strings for the proposer prompt."""
        return [c.query for c in self.exemplars[:n]]


def cluster_failures(
    failing_cases: list[EvalCase],
    rater_results: list[RaterResult],
    min_cluster_size: int = 5,
    model_name: str = "all-MiniLM-L6-v2",
) -> list[FailureCluster]:
    """Cluster failing eval cases by semantic similarity.

    Uses sentence-transformers for embeddings and HDBSCAN for clustering.
    Falls back to a single cluster when there are too few failures or
    when the optional dependencies are not installed.

    Args:
        failing_cases: EvalCase instances that failed at least one rater.
        rater_results: Corresponding RaterResult instances.
        min_cluster_size: HDBSCAN min_cluster_size parameter.
        model_name: sentence-transformers model name.

    Returns:
        List of FailureCluster instances sorted by size descending.
    """
    if not failing_cases:
        return []

    texts = [c.query for c in failing_cases]

    try:
        import hdbscan  # type: ignore[import-untyped]
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        encoder = SentenceTransformer(model_name)
        embeddings = encoder.encode(texts, show_progress_bar=False)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min(min_cluster_size, max(2, len(failing_cases) // 3)),
            metric="euclidean",
        )
        labels = clusterer.fit_predict(embeddings)

        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(idx)

    except ImportError:
        logger.warning(
            "sentence-transformers or hdbscan not installed — using single cluster fallback"
        )
        # Single cluster: all failures together
        labels = [0] * len(failing_cases)
        clusters = {0: list(range(len(failing_cases)))}

    result: list[FailureCluster] = []
    fail_map: dict[str, list[RaterResult]] = {}
    for r in rater_results:
        fail_map.setdefault(r.case_id, []).append(r)

    for cluster_id, indices in clusters.items():
        if cluster_id == -1:
            # HDBSCAN noise cluster — skip
            continue
        cluster_cases = [failing_cases[i] for i in indices]
        cluster_raters = [
            r for c in cluster_cases for r in fail_map.get(c.case_id, [])
        ]
        # Determine dominant failure mode by rater id frequency
        rater_counts: dict[str, int] = {}
        for r in cluster_raters:
            if not r.passed:
                rater_counts[r.rater] = rater_counts.get(r.rater, 0) + 1
        failure_mode = max(rater_counts, key=lambda k: rater_counts[k]) if rater_counts else ""

        result.append(
            FailureCluster(
                cluster_id=cluster_id,
                exemplars=cluster_cases,
                rater_results=cluster_raters,
                failure_mode=failure_mode,
                size=len(cluster_cases),
            )
        )

    result.sort(key=lambda c: c.size, reverse=True)
    return result
