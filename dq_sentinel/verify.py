"""VERIFY step (agent-loop step 7): confirm the remediation worked.

After step 6 invokes a Fivetran write tool, this step:
  1. Polls the connection until the triggered sync completes (or times out),
  2. Re-runs every DQ check that failed in step 3 (INSPECT),
  3. Records before/after metrics and a verification_result,
  4. Reports the time spent waiting on the sync so the agent loop can break TTR
     into agent-attributable vs sync-latency-attributable (spec
     diagnosis-and-remediation §"Time-to-resolution metric").

Spec deviation (verified live 2026-06-02): the spec names `get_connection_state`
for polling, but `GET /v1/connections/{id}/state` returns HTTP 405 on the live
Fivetran API. The reliable signal is `get_connection_details`, whose
`status.sync_state` + `succeeded_at` / `failed_at` tell us when the on-demand
sync finishes. We poll that instead.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from dq_sentinel import bq, mcp_client

POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 30 * 60


async def connection_details(connection_id: str) -> dict[str, Any]:
    r = await mcp_client.call_tool(
        "get_connection_details", {"connection_id": connection_id}, allow_writes=False
    )
    data = r["result"]
    return data.get("data", data) if isinstance(data, dict) else {}


def _sync_fields(details: dict[str, Any]) -> dict[str, Any]:
    status = details.get("status", {}) or {}
    return {
        "sync_state": status.get("sync_state"),
        "succeeded_at": details.get("succeeded_at"),
        "failed_at": details.get("failed_at"),
    }


async def poll_until_synced(
    connection_id: str,
    baseline_succeeded_at: str | None,
    baseline_failed_at: str | None,
    *,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll connection details until a NEW sync result appears past the baseline.

    Completion = `succeeded_at` advances beyond the pre-ACT value (-> "synced") or
    `failed_at` advances (-> "failed"). On timeout -> "timed_out".
    """
    started = time.monotonic()
    polls = 0
    while True:
        details = await connection_details(connection_id)
        f = _sync_fields(details)
        polls += 1
        if f["failed_at"] and f["failed_at"] != baseline_failed_at:
            outcome = "failed"
        elif f["succeeded_at"] and f["succeeded_at"] != baseline_succeeded_at:
            outcome = "synced"
        else:
            outcome = None
        elapsed = time.monotonic() - started
        if outcome is not None:
            return {
                "result": outcome,
                "completed": outcome == "synced",
                "sync_wait_seconds": round(elapsed, 1),
                "polls": polls,
                "sync_state": f["sync_state"],
                "succeeded_at": f["succeeded_at"],
            }
        if elapsed + interval > timeout:
            return {
                "result": "timed_out",
                "completed": False,
                "sync_wait_seconds": round(elapsed, 1),
                "polls": polls,
                "sync_state": f["sync_state"],
                "succeeded_at": f["succeeded_at"],
            }
        await asyncio.sleep(interval)


def rerun_failed_checks(failed_checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-run each previously-failed DQ check; return the fresh results."""
    return [bq.rerun(c) for c in failed_checks]


def _before_after(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for b, a in zip(before, after):
        rows.append(
            {
                "check_name": b.get("check_name"),
                "table": b.get("table"),
                "column": b.get("column"),
                "before_value": b.get("current_value"),
                "after_value": a.get("current_value"),
                "baseline_value": a.get("baseline_value"),
                "before_passed": b.get("passed"),
                "after_passed": a.get("passed"),
            }
        )
    return rows


async def verify(
    connection_id: str,
    failed_checks: list[dict[str, Any]],
    *,
    executed_write: bool,
    baseline_succeeded_at: str | None = None,
    baseline_failed_at: str | None = None,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run step 7. Returns the verification block of the incident report.

    `executed_write` is False for action=manual (no sync was triggered) — we skip
    polling and just re-check whether the issue self-resolved.
    """
    poll: dict[str, Any] = {"result": "skipped", "sync_wait_seconds": 0.0, "polls": 0}
    if executed_write:
        poll = await poll_until_synced(
            connection_id,
            baseline_succeeded_at,
            baseline_failed_at,
            interval=interval,
            timeout=timeout,
        )
        if poll["result"] == "timed_out":
            return {
                "verification_result": "timed_out",
                "sync_wait_seconds": poll["sync_wait_seconds"],
                "polls": poll["polls"],
                "message": "sync still in progress after timeout",
                "before_after": [],
            }

    after = rerun_failed_checks(failed_checks)
    all_pass = all(c.get("passed") for c in after)
    if executed_write and poll["result"] == "failed":
        result = "failed"
    elif all_pass:
        result = "passed"
    else:
        result = "failed"

    return {
        "verification_result": result,
        "sync_wait_seconds": poll["sync_wait_seconds"],
        "polls": poll["polls"],
        "rechecked": after,
        "before_after": _before_after(failed_checks, after),
    }
