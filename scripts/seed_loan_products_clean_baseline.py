"""Seed the KNOWN-CLEAN baseline for loan_products (schema-drift demo, PRD §8 #1).

loan_products is left in the drifted state (source column base_apr renamed to
headline_apr) as a fixture, so we can't capture a clean baseline by reading the
live table. Instead we reconstruct it from the source-of-truth clean schema
(demo-data/csv/loan_products.csv): columns product_id, product_name, category,
base_apr, is_active — i.e. the current columns MINUS the drifted-in `headline_apr`,
with base_apr fully populated (null_rate 0).

After seeding, the loop on loan_products detects the drift: schema_mismatch
(headline_apr added) + null_rate spike on base_apr. NOTE: reaching *resolved*
still requires reverting the Sheet header (base_apr) before approval — a normal
resync re-imports the still-drifted source.

Run:
    export GOOGLE_APPLICATION_CREDENTIALS=.secrets/dq-sentinel-runtime.json
    export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=agent-era GOOGLE_CLOUD_LOCATION=global
    uv run scripts/seed_loan_products_clean_baseline.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from dq_sentinel import bq

CONNECTION_ID = "subjected_synthesis"
DRIFTED_IN_COLUMN = "headline_apr"
CLEAN_DATA_COLS = ["product_id", "product_name", "category", "base_apr", "is_active"]


def main() -> int:
    current = bq.columns("loan_products")
    clean_cols = sorted(current - {DRIFTED_IN_COLUMN})  # fingerprint incl meta cols
    row_count = list(
        bq.client().query(f"SELECT COUNT(*) c FROM {bq._fqtn('loan_products')}").result()
    )[0]["c"]
    now = datetime.now(timezone.utc).isoformat()

    def row(metric, value, column):
        return {"connection_id": CONNECTION_ID, "table_name": "loan_products",
                "column_name": column, "metric": metric, "metric_value": value,
                "metric_version": 1, "captured_at": now}

    rows = [
        row("row_count", str(row_count), None),
        row("schema_fingerprint", json.dumps(clean_cols), None),
    ]
    # clean data had no nulls (base_apr was populated before the rename)
    rows += [row("null_rate", "0.000000", c) for c in CLEAN_DATA_COLS]

    bq._append_baselines(rows)
    print(f"seeded clean baseline for loan_products ({len(rows)} rows)")
    print(f"  clean schema fingerprint: {clean_cols}")
    print(f"  (current table has the drifted-in column {DRIFTED_IN_COLUMN!r} -> drift is now detectable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
