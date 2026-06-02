"""Integration test for the BQ DQ check library (section 4).

Happy path: seed clean tables, run checks, expect PASS.
Fail path: inject a known-clean baseline for the (currently drifted) loan_products
table, then run schema_mismatch + null_rate(base_apr) and expect FAIL — this
mirrors "seeded clean, then the source renamed base_apr -> headline_apr".

Run:
    export GOOGLE_APPLICATION_CREDENTIALS=.secrets/dq-sentinel-runtime.json
    uv run scripts/test_dq_checks.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from dq_sentinel import bq


def show(r: dict) -> None:
    flag = "PASS" if r["passed"] else "FAIL"
    print(f"  [{flag}] {r['check_name']:16} {r['table']}"
          f"{'.' + r['column'] if r['column'] else '':<14}"
          f" cur={r['current_value']} base={r['baseline_value']} dev={r['deviation']} sev={r['severity']}")


def main() -> int:
    print("=== seed clean baselines (account_holders, transactions) ===")
    for t in ("account_holders", "transactions"):
        info = bq.seed_baselines(t, connection_id=f"conn_{t}")
        print(f"  seeded {t}: {info['rows_written']} rows, row_count={info['row_count']}")

    print("\n=== happy path checks (expect PASS) ===")
    show(bq.dq_check_row_count("transactions"))
    show(bq.dq_check_null_rate("account_holders", "kyc_status"))
    show(bq.dq_check_freshness("transactions", sla_minutes=10_000))  # wide SLA; just synced
    show(bq.dq_check_schema_mismatch("account_holders"))

    print("\n=== inject KNOWN-CLEAN baseline for loan_products (pre-drift) ===")
    now = datetime.now(timezone.utc).isoformat()
    clean_cols = ["_fivetran_synced", "_row", "base_apr", "category",
                  "is_active", "product_id", "product_name"]
    bq._append_baselines([
        {"connection_id": "conn_loan_products", "table_name": "loan_products",
         "column_name": None, "metric": "schema_fingerprint",
         "metric_value": json.dumps(sorted(clean_cols)), "metric_version": 1, "captured_at": now},
        {"connection_id": "conn_loan_products", "table_name": "loan_products",
         "column_name": "base_apr", "metric": "null_rate",
         "metric_value": "0.000000", "metric_version": 1, "captured_at": now},
    ])
    print("  injected clean fingerprint + base_apr null_rate=0")

    print("\n=== fail path checks on drifted loan_products (expect FAIL) ===")
    sm = bq.dq_check_schema_mismatch("loan_products")
    show(sm)
    nr = bq.dq_check_null_rate("loan_products", "base_apr")
    show(nr)

    ok = (not sm["passed"]) and (not nr["passed"]) and ("headline_apr" in sm["deviation"]["added"])
    print(f"\nfail-path detectors fired correctly: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
