"""BigQuery data-quality checks + baseline storage for DQ Sentinel.

Design constraints (spec `bigquery-dq-checks`):
- The model never supplies free-form SQL. Table names are validated against a
  known allowlist; column names are validated against INFORMATION_SCHEMA. All
  SQL is templated here from the PRD Appendix B patterns.
- Baselines live in one append-only table `dq_sentinel.baselines`; reads take the
  most recent row by captured_at.
- Each check returns a uniform structured result the DIAGNOSE step consumes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from dq_sentinel import config

# Tables DQ Sentinel is allowed to touch (the Fivetran-landed demo tables).
KNOWN_TABLES = {"account_holders", "transactions", "loan_products"}

_CLIENT: bigquery.Client | None = None


def client() -> bigquery.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = bigquery.Client(project=config.GCP_PROJECT)
    return _CLIENT


# --- safety helpers --------------------------------------------------------
def _fqtn(table: str) -> str:
    """Validate a table name against the allowlist and return its backticked FQN."""
    if table not in KNOWN_TABLES:
        raise ValueError(f"unknown table {table!r}; allowed: {sorted(KNOWN_TABLES)}")
    return f"`{config.GCP_PROJECT}.{config.BQ_DATASET}.{table}`"


def columns(table: str) -> set[str]:
    """Live column set for a table, from INFORMATION_SCHEMA (also validates table)."""
    _fqtn(table)
    q = (
        f"SELECT column_name FROM `{config.GCP_PROJECT}.{config.BQ_DATASET}`"
        ".INFORMATION_SCHEMA.COLUMNS WHERE table_name = @t"
    )
    job = client().query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("t", "STRING", table)]
        ),
    )
    return {r["column_name"] for r in job.result()}


def _result(
    check_name: str,
    table: str,
    column: str | None,
    current_value: Any,
    baseline_value: Any,
    deviation: float | None,
    passed: bool,
    severity: str,
) -> dict[str, Any]:
    return {
        "check_name": check_name,
        "table": table,
        "column": column,
        "current_value": current_value,
        "baseline_value": baseline_value,
        "deviation": deviation,
        "passed": passed,
        "severity": severity if not passed else "OK",
    }


# --- baseline storage ------------------------------------------------------
def _baselines_fqtn() -> str:
    return f"{config.GCP_PROJECT}.{config.BQ_DATASET}.baselines"


def get_baseline(table: str, metric: str, column: str | None = None) -> str | None:
    """Most recent baseline metric_value for (table, metric, column), or None."""
    col_clause = "column_name = @c" if column is not None else "column_name IS NULL"
    q = (
        f"SELECT metric_value FROM `{_baselines_fqtn()}` "
        f"WHERE table_name = @t AND metric = @m AND {col_clause} "
        "ORDER BY captured_at DESC LIMIT 1"
    )
    params = [
        bigquery.ScalarQueryParameter("t", "STRING", table),
        bigquery.ScalarQueryParameter("m", "STRING", metric),
    ]
    if column is not None:
        params.append(bigquery.ScalarQueryParameter("c", "STRING", column))
    rows = list(client().query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return rows[0]["metric_value"] if rows else None


def _append_baselines(rows: list[dict[str, Any]]) -> None:
    # Load job (not streaming insert): rows are immediately queryable, so a
    # seed immediately followed by a check reads back reliably.
    job = client().load_table_from_json(
        rows,
        _baselines_fqtn(),
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
    )
    job.result()
    if job.errors:
        raise RuntimeError(f"baseline load failed: {job.errors}")


def seed_baselines(table: str, connection_id: str = "") -> dict[str, Any]:
    """Capture row_count, per-column null_rate, and a schema fingerprint for a
    table into `dq_sentinel.baselines`. Run once against KNOWN-GOOD data before
    the agent loop runs against that table (spec `agent-loop`)."""
    fq = _fqtn(table)
    cols = columns(table)
    now = datetime.now(timezone.utc).isoformat()
    data_cols = sorted(c for c in cols if not c.startswith("_"))

    # one pass: total + null count per data column
    null_exprs = ", ".join(f"COUNTIF(`{c}` IS NULL) AS nulls_{i}" for i, c in enumerate(data_cols))
    q = f"SELECT COUNT(*) AS total{', ' + null_exprs if null_exprs else ''} FROM {fq}"
    row = list(client().query(q).result())[0]
    total = row["total"]

    rows: list[dict[str, Any]] = []

    def base_row(metric: str, value: str, column: str | None) -> dict[str, Any]:
        return {
            "connection_id": connection_id,
            "table_name": table,
            "column_name": column,
            "metric": metric,
            "metric_value": value,
            "metric_version": 1,
            "captured_at": now,
        }

    rows.append(base_row("row_count", str(total), None))
    rows.append(base_row("schema_fingerprint", json.dumps(sorted(cols)), None))
    for i, c in enumerate(data_cols):
        null_rate = (row[f"nulls_{i}"] / total) if total else 0.0
        rows.append(base_row("null_rate", f"{null_rate:.6f}", c))

    _append_baselines(rows)
    return {"table": table, "rows_written": len(rows), "row_count": total, "columns": data_cols}


# --- DQ checks -------------------------------------------------------------
def dq_check_row_count(table: str, connection_id: str = "", deviation_threshold: float = 0.30) -> dict[str, Any]:
    """Row count vs baseline; fail if |Δ| exceeds deviation_threshold (default 30%)."""
    fq = _fqtn(table)
    current = list(client().query(f"SELECT COUNT(*) AS c FROM {fq}").result())[0]["c"]
    base_raw = get_baseline(table, "row_count")
    if base_raw is None:
        return _result("row_count", table, None, current, None, None, True, "OK")
    base = float(base_raw)
    deviation = abs(current - base) / base if base else (0.0 if current == 0 else 1.0)
    passed = deviation <= deviation_threshold
    return _result("row_count", table, None, current, int(base), round(deviation, 4), passed, "HIGH")


def dq_check_null_rate(table: str, column: str, connection_id: str = "", multiplier: float = 2.0) -> dict[str, Any]:
    """Null rate for a column vs baseline; fail if current > multiplier×baseline
    (or, when baseline is zero, if any nulls appear)."""
    fq = _fqtn(table)
    cols = columns(table)
    if column not in cols:
        raise ValueError(f"unknown column {column!r} on {table!r}; columns: {sorted(cols)}")
    row = list(
        client().query(f"SELECT COUNTIF(`{column}` IS NULL) AS null_ct, COUNT(*) AS total_ct FROM {fq}").result()
    )[0]
    current = (row["null_ct"] / row["total_ct"]) if row["total_ct"] else 0.0
    base_raw = get_baseline(table, "null_rate", column)
    if base_raw is None:
        return _result("null_rate", table, column, round(current, 4), None, None, True, "OK")
    base = float(base_raw)
    if base == 0:
        passed = current == 0
        deviation = current  # absolute spike from zero
    else:
        passed = current <= multiplier * base
        deviation = round(current / base, 4)
    return _result("null_rate", table, column, round(current, 4), round(base, 4), deviation, passed, "HIGH")


def dq_check_freshness(table: str, connection_id: str = "", sla_minutes: int = 180) -> dict[str, Any]:
    """Minutes since the latest _fivetran_synced; fail if older than sla_minutes."""
    fq = _fqtn(table)
    stale = list(
        client()
        .query(f"SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(_fivetran_synced), MINUTE) AS m FROM {fq}")
        .result()
    )[0]["m"]
    passed = stale is not None and stale <= sla_minutes
    return _result("freshness", table, None, stale, sla_minutes, None, passed, "MEDIUM")


def dq_check_schema_mismatch(table: str, connection_id: str = "") -> dict[str, Any]:
    """Live column set vs the baseline schema_fingerprint; fail on any diff."""
    current_cols = sorted(columns(table))
    base_raw = get_baseline(table, "schema_fingerprint")
    if base_raw is None:
        return _result("schema_mismatch", table, None, current_cols, None, None, True, "OK")
    base_cols = json.loads(base_raw)
    added = sorted(set(current_cols) - set(base_cols))
    removed = sorted(set(base_cols) - set(current_cols))
    passed = not added and not removed
    diff = {"added": added, "removed": removed}
    return _result("schema_mismatch", table, None, current_cols, base_cols, diff, passed, "MEDIUM")


# --- re-run dispatch (step 7 VERIFY) ---------------------------------------
# Maps a prior check result back to its check function so step 7 can re-run
# exactly the checks that failed in step 3 (spec agent-loop / diagnosis §verify).
def rerun(check: dict[str, Any]) -> dict[str, Any]:
    """Re-run a single DQ check given a prior result dict (uses its table/column)."""
    name = check.get("check_name")
    table = check["table"]
    if name == "row_count":
        return dq_check_row_count(table)
    if name == "null_rate":
        return dq_check_null_rate(table, check["column"])
    if name == "freshness":
        return dq_check_freshness(table)
    if name == "schema_mismatch":
        return dq_check_schema_mismatch(table)
    raise ValueError(f"cannot re-run unknown check {name!r}")
