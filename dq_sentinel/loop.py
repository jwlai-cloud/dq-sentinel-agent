"""The 7-step DQ Sentinel agent loop (spec `agent-loop`).

This module sequences the steps deterministically as application code. Gemini is
invoked only inside step 4 (DIAGNOSE, see diagnose.py); every other step is plain
code. This is what makes the approval gate structural (design.md D4): the model
never has a Fivetran write tool in scope, and step 6 runs only after step 5
returns "approved".

Steps:
  1 SCAN     - Fivetran list_connections / connection details (read-only MCP)
  2 DETECT   - flag Fivetran-level issues + (via INSPECT) data-level issues
  3 INSPECT  - run BQ DQ checks on the connection's tables
  4 DIAGNOSE - Gemini -> propose_remediation, validated, <=2 retries
  5 APPROVE  - human gate (injected callback); reject -> one revised diagnosis
  6 ACT      - map approved payload -> one Fivetran write tool (act.py)
  7 VERIFY   - poll sync, re-run failed checks, before/after + TTR (verify.py)

Every run emits a structured incident report (resolved / unresolved / no-issue /
baseline_missing / diagnosis_failed).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from dq_sentinel import act, bq, mcp_client, verify
from dq_sentinel.diagnose import diagnose, validate_payload

# An approval callback receives (proposal, planned_call) and returns a decision:
#   {"decision": "approved"|"rejected"|"modified", "targets": [...], "reason": str}
ApprovalFn = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]

MAX_DIAGNOSIS_ATTEMPTS = 3  # 1 initial + 2 retries (spec diagnosis-and-remediation)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


# --- step 1 SCAN -----------------------------------------------------------
async def scan_all() -> list[dict[str, Any]]:
    """list_connections across the account (read-only). Returns flat connection items."""
    r = await mcp_client.call_tool("list_connections", {}, allow_writes=False)
    data = r["result"]
    items = data.get("data", {}).get("items", []) if isinstance(data, dict) else []
    return items


async def connection_details(connection_id: str) -> dict[str, Any]:
    return await verify.connection_details(connection_id)


# --- step 2 DETECT ---------------------------------------------------------
def detect_fivetran_issues(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag Fivetran-level problems from a connection's status."""
    status = details.get("status", {}) or {}
    issues: list[dict[str, Any]] = []
    if status.get("setup_state") not in (None, "connected"):
        issues.append({"kind": "setup", "detail": status.get("setup_state")})
    if status.get("sync_state") in ("broken", "failed"):
        issues.append({"kind": "sync", "detail": status.get("sync_state")})
    if details.get("failed_at"):
        issues.append({"kind": "failed_sync", "detail": details.get("failed_at")})
    for w in status.get("warnings", []) or []:
        issues.append({"kind": "warning", "detail": w})
    return issues


# --- step 3 INSPECT --------------------------------------------------------
async def connection_tables(connection_id: str) -> tuple[str | None, list[str]]:
    """Return (schema_name, [table names]) for a connection, intersected with the
    DQ allowlist (bq.KNOWN_TABLES)."""
    r = await mcp_client.call_tool(
        "get_connection_schema_config", {"connection_id": connection_id}, allow_writes=False
    )
    data = (r["result"] or {}).get("data", {}) if isinstance(r["result"], dict) else {}
    schemas = data.get("schemas", {}) or {}
    schema_name = next(iter(schemas), None)
    tables: list[str] = []
    for sch in schemas.values():
        for tname, t in (sch.get("tables", {}) or {}).items():
            if t.get("enabled", True) and tname in bq.KNOWN_TABLES:
                tables.append(tname)
    return schema_name, tables


def inspect_table(table: str) -> list[dict[str, Any]]:
    """Run the full DQ check suite on one table (row count, per-column null rate,
    freshness, schema drift). Returns all check results."""
    results = [
        bq.dq_check_row_count(table),
        bq.dq_check_freshness(table),
        bq.dq_check_schema_mismatch(table),
    ]
    for col in sorted(c for c in bq.columns(table) if not c.startswith("_")):
        results.append(bq.dq_check_null_rate(table, col))
    return results


def _has_baseline(table: str) -> bool:
    return bq.get_baseline(table, "row_count") is not None


# --- step 4 DIAGNOSE (validated, with retry) -------------------------------
async def diagnose_validated(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Run DIAGNOSE with up to MAX_DIAGNOSIS_ATTEMPTS, feeding validation errors
    back to the model. Returns (proposal, errors): proposal is None if all attempts
    failed validation (-> diagnosis_failed)."""
    feedback: str | None = None
    last_errs: list[str] = ["model never called propose_remediation"]
    for _ in range(MAX_DIAGNOSIS_ATTEMPTS):
        proposal = await diagnose(payload, feedback=feedback)
        if proposal is None:
            feedback = "You did not call propose_remediation. Call it exactly once."
            last_errs = ["model never called propose_remediation"]
            continue
        errs = validate_payload(proposal)
        if not errs:
            return proposal, []
        last_errs = errs
        feedback = "Your previous proposal was invalid: " + "; ".join(errs) + ". Fix and re-call propose_remediation."
    return None, last_errs


# --- full loop -------------------------------------------------------------
async def run_loop(
    connection_id: str,
    *,
    approval: ApprovalFn,
    poll_interval: float = verify.POLL_INTERVAL_SECONDS,
    poll_timeout: float = verify.POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute the 7-step loop for one connection and return its incident report."""
    start = time.monotonic()
    report: dict[str, Any] = {
        "connection_id": connection_id,
        "triggered_at": _now_iso(),
        "detected_issues": [],
        "root_cause_hypothesis": None,
        "remediation_proposed": None,
        "approval_decision": None,
        "action_taken": None,
        "verification_result": None,
        "before_metrics": [],
        "after_metrics": [],
        "time_to_resolution": None,
    }

    def finish(status: str, sync_wait: float = 0.0) -> dict[str, Any]:
        total = time.monotonic() - start
        report["status"] = status
        report["time_to_resolution"] = {
            "total": _fmt_duration(total),
            "agent": _fmt_duration(max(0.0, total - sync_wait)),
            "sync_wait": _fmt_duration(sync_wait),
            "total_seconds": round(total, 1),
            "sync_wait_seconds": round(sync_wait, 1),
        }
        return report

    # STEP 1 SCAN + STEP 2 DETECT (Fivetran level)
    details = await connection_details(connection_id)
    report["fivetran_status"] = details.get("status", {})
    fivetran_issues = detect_fivetran_issues(details)

    # tables to inspect
    schema_name, tables = await connection_tables(connection_id)
    if not tables:
        report["detected_issues"] = fivetran_issues
        report["message"] = "no DQ-allowlisted tables on this connection"
        return finish("no-issue")

    # baseline precondition (spec: terminate before inspect/diagnose/act)
    missing = [t for t in tables if not _has_baseline(t)]
    if missing:
        report["message"] = f"baseline missing for {missing} — run seed_baselines first"
        return finish("baseline_missing")

    # STEP 3 INSPECT
    all_checks: list[dict[str, Any]] = []
    for t in tables:
        all_checks.extend(inspect_table(t))
    failed_checks = [c for c in all_checks if not c.get("passed")]
    report["detected_issues"] = fivetran_issues + failed_checks
    report["before_metrics"] = failed_checks

    if not failed_checks and not fivetran_issues:
        return finish("no-issue")
    if not failed_checks:
        # Fivetran-level issue only, no failed data checks to feed diagnosis;
        # still surface it but nothing for the data-diagnosis path to act on.
        report["message"] = "Fivetran-level issue detected; no failed DQ checks"
        return finish("unresolved")

    # primary affected table = the one with the most failures
    by_table: dict[str, int] = {}
    for c in failed_checks:
        by_table[c["table"]] = by_table.get(c["table"], 0) + 1
    primary_table = max(by_table, key=by_table.get)

    payload = {
        "connection": {
            "id": connection_id,
            "schema": details.get("schema"),
            "service": details.get("service"),
            "status": details.get("status", {}),
        },
        "table": primary_table,
        "failed_checks": [c for c in failed_checks if c["table"] == primary_table],
    }

    # STEP 4 DIAGNOSE (validated, <=2 retries)
    proposal, errs = await diagnose_validated(payload)
    if proposal is None:
        report["message"] = f"diagnosis failed validation after retries: {errs}"
        report["verification_result"] = "diagnosis_failed"
        return finish("diagnosis_failed")
    report["root_cause_hypothesis"] = proposal.get("root_cause")
    report["remediation_proposed"] = proposal

    # STEP 5 APPROVE — gate. Reject allows one revised diagnosis (spec).
    decision: dict[str, Any] | None = None
    for attempt in range(2):
        planned = act.planned_call(proposal, connection_id)
        decision = await approval(proposal, planned)
        if decision.get("decision") == "modified" and decision.get("targets") is not None:
            proposal = {**proposal, "targets": decision["targets"]}
            report["remediation_proposed"] = proposal
            decision = {**decision, "decision": "approved"}
        if decision.get("decision") == "approved":
            break
        # rejected
        if attempt == 0:
            reason = decision.get("reason") or "user rejected the proposal"
            revised, errs = await diagnose_validated({**payload, "rejection_reason": reason})
            if revised is not None:
                proposal = revised
                report["root_cause_hypothesis"] = proposal.get("root_cause")
                report["remediation_proposed"] = proposal
                continue
        # second rejection or no revised diagnosis
        report["approval_decision"] = {"decision": "rejected", "reason": decision.get("reason")}
        report["message"] = "remediation rejected by user"
        return finish("unresolved")

    report["approval_decision"] = decision

    # STEP 6 ACT — capture pre-write sync markers for the verify poll
    pre = await connection_details(connection_id)
    pre_succeeded = pre.get("succeeded_at")
    pre_failed = pre.get("failed_at")

    act_result = await act.act(proposal, connection_id)
    report["action_taken"] = act_result

    # STEP 7 VERIFY
    v = await verify.verify(
        connection_id,
        payload["failed_checks"],
        executed_write=act_result["executed"],
        baseline_succeeded_at=pre_succeeded,
        baseline_failed_at=pre_failed,
        interval=poll_interval,
        timeout=poll_timeout,
    )
    report["verification_result"] = v["verification_result"]
    report["after_metrics"] = v.get("before_after", [])
    report["verification"] = v

    status = {"passed": "resolved", "failed": "unresolved", "timed_out": "unresolved"}.get(
        v["verification_result"], "unresolved"
    )
    return finish(status, sync_wait=v.get("sync_wait_seconds", 0.0))
