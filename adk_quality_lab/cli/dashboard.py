"""CLI: refresh BigQuery view backing Looker Studio dashboard."""

from __future__ import annotations

import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_RUNS_SUMMARY_DDL = """
CREATE OR REPLACE VIEW `{project}.{dataset}.runs_summary_v` AS
SELECT
  run_id,
  variant,
  surface,
  iteration,
  aggregate_score,
  JSON_VALUE(category_scores, '$.F1') AS f1_score,
  JSON_VALUE(category_scores, '$.F2') AS f2_score,
  TIMESTAMP_MILLIS(CAST(JSON_VALUE(meta, '$.timestamp_ms') AS INT64)) AS run_at
FROM `{project}.{dataset}.runs`
ORDER BY run_at DESC;
"""


def main() -> None:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "adk-quality-lab-tung")
    dataset = os.environ.get("BQ_DATASET", "adk_quality_lab")

    try:
        from google.cloud import bigquery  # type: ignore[import-untyped]

        client = bigquery.Client(project=project)
        ddl = _RUNS_SUMMARY_DDL.format(project=project, dataset=dataset)
        job = client.query(ddl)
        job.result()
        logger.info("Refreshed BigQuery view %s.%s.runs_summary_v", project, dataset)
    except Exception as exc:
        logger.error("BigQuery refresh failed: %s", exc)


if __name__ == "__main__":
    main()
