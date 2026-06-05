"""The job engine + approval-gate bridge (locked design, workflow winner 8.95).

A run is a detached asyncio task on the uvicorn event loop. The human approval
gate (loop.py step 5) is reconciled with the HTTP lifecycle by an asyncio.Future:
the injected `approval` callback parks the run_loop coroutine on a Future held in
the process-global RUNS registry; an async HTTP POST resolves it. No request
thread is ever held across the human wait OR the 30-minute verify poll.

Why the structural gate survives: the web `approval` has the SAME signature as
the CLI one (loop.ApprovalFn), so run_loop/act/verify are untouched. act.act()
(the only allow_writes=True caller) is lexically downstream of `await approval`;
the Future only resolves on a real POST /decision. Gemini never holds a write
tool. The seam is the loop's own await — not a UI if-check.

Thread-safety: the decision route is async (runs on the same event loop), but we
still resolve via loop.call_soon_threadsafe(captured at task launch) so the design
is correct even if a caller ever dispatches from a threadpool.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from dq_sentinel import loop as agent_loop
from dq_sentinel.web import store

# Live, in-process run registry. Source of truth while a run is in flight.
RUNS: dict[str, "RunHandle"] = {}

# Status values surfaced to the UI.
ACTIVE_STATUSES = {
    "detecting", "inspecting", "diagnosing", "awaiting_approval",
    "rediagnosing", "acting", "verifying",
}

# loop progress stage -> coarse run status for the UI
_STAGE_STATUS = {
    "scanning": "detecting",
    "detecting": "detecting",
    "inspecting": "inspecting",
    "diagnosing": "diagnosing",
    "acting": "acting",
    "verifying": "verifying",
}


@dataclass
class RunHandle:
    run_id: str
    connection_id: str
    loop: asyncio.AbstractEventLoop
    status: str = "detecting"
    created_at: float = field(default_factory=time.time)
    # gate state
    approval_future: asyncio.Future | None = None
    pending_proposal: dict[str, Any] | None = None
    pending_planned_call: dict[str, Any] | None = None
    gate_enter_ts: float | None = None  # monotonic
    gate_exit_ts: float | None = None
    gate_wait_seconds: float = 0.0  # accumulated across re-diagnosis cycles
    # progress + result
    progress_log: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    error: str | None = None
    # strong ref to the detached driver task — asyncio only holds a weak ref, so
    # without this the run could be garbage-collected mid-flight.
    task: "asyncio.Task | None" = None


# --- progress callback ------------------------------------------------------
def _make_progress(run_id: str):
    def progress(stage: str, detail: dict[str, Any]) -> None:
        h = RUNS.get(run_id)
        if h is None:
            return
        h.progress_log.append({"stage": stage, "detail": detail, "ts": time.time()})
        new_status = _STAGE_STATUS.get(stage)
        if new_status:
            h.status = new_status
        store.set_state(run_id, {"status": h.status, "last_stage": stage})

    return progress


# --- approval callback (the gate bridge) ------------------------------------
def _make_approval(run_id: str) -> agent_loop.ApprovalFn:
    async def approval(proposal: dict[str, Any], planned_call: dict[str, Any]) -> dict[str, Any]:
        h = RUNS[run_id]
        h.pending_proposal = proposal
        h.pending_planned_call = planned_call
        h.gate_enter_ts = time.monotonic()
        h.status = "awaiting_approval"
        store.set_state(run_id, {
            "status": "awaiting_approval",
            "proposal": proposal,
            "planned_call": planned_call,
        })
        # A FRESH future per gate entry — re-entrant for the reject→re-diagnose path.
        h.approval_future = h.loop.create_future()
        decision = await h.approval_future  # coroutine PARKS here; no thread/request held

        h.gate_exit_ts = time.monotonic()
        h.gate_wait_seconds += h.gate_exit_ts - h.gate_enter_ts
        h.approval_future = None
        if decision.get("decision") == "rejected":
            # run_loop will re-diagnose then re-enter this gate; flip the UI off the
            # now-stale proposal until the revised one arrives.
            h.status = "rediagnosing"
            h.pending_proposal = None
            h.pending_planned_call = None
            store.set_state(run_id, {"status": "rediagnosing"})
        return decision

    return approval


# --- the detached run driver ------------------------------------------------
async def _drive(run_id: str, connection_id: str) -> None:
    h = RUNS[run_id]
    try:
        report = await agent_loop.run_loop(
            connection_id,
            approval=_make_approval(run_id),
            progress=_make_progress(run_id),
            poll_interval=15,
            poll_timeout=1800,
        )
        h.report = report
        h.status = report.get("status", "done")
        store.set_state(run_id, {"status": h.status, "report": report})
        store.append_history(report)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        h.error = f"{type(exc).__name__}: {exc}"
        h.status = "error"
        store.set_state(run_id, {"status": "error", "error": h.error})


# --- public API (called by the FastAPI routes) ------------------------------
def start_run(connection_id: str) -> str:
    """Mint a run, register it, and schedule the detached driver. Returns run_id.

    MUST be called from inside a coroutine running on the serving event loop so
    the captured loop matches the one the Future is created on.
    """
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = RunHandle(
        run_id=run_id,
        connection_id=connection_id,
        loop=asyncio.get_running_loop(),
    )
    store.set_state(run_id, {
        "status": "detecting",
        "connection_id": connection_id,
        "triggered_at": agent_loop._now_iso(),
    })
    RUNS[run_id].task = asyncio.create_task(_drive(run_id, connection_id))
    return run_id


def snapshot(run_id: str) -> dict[str, Any] | None:
    """Poll view of a run: live RunHandle merged with the durable store, with the
    TTR human-think-time correction applied (gate wait subtracted from agent time)."""
    h = RUNS.get(run_id)
    if h is None:
        return store.get_state(run_id)  # may have been swept/persisted only

    snap: dict[str, Any] = {
        "run_id": run_id,
        "connection_id": h.connection_id,
        "status": h.status,
        "proposal": h.pending_proposal,
        "planned_call": h.pending_planned_call,
        "awaiting_decision": h.approval_future is not None and not h.approval_future.done(),
        "progress_log": h.progress_log,
        "report": h.report,
        "error": h.error,
        "gate_wait_seconds": round(h.gate_wait_seconds, 1),
    }
    if h.report and h.report.get("time_to_resolution"):
        ttr = dict(h.report["time_to_resolution"])
        total = ttr.get("total_seconds", 0.0)
        sync_wait = ttr.get("sync_wait_seconds", 0.0)
        agent_only = max(0.0, total - sync_wait - h.gate_wait_seconds)
        ttr["agent_seconds_corrected"] = round(agent_only, 1)
        ttr["human_wait_seconds"] = round(h.gate_wait_seconds, 1)
        ttr["agent"] = agent_loop._fmt_duration(agent_only)
        ttr["human_wait"] = agent_loop._fmt_duration(h.gate_wait_seconds)
        snap["time_to_resolution"] = ttr
    return snap


def submit_decision(
    run_id: str, decision: str, targets: list[str] | None = None, reason: str = ""
) -> dict[str, Any]:
    """Resolve the parked approval future for a run. Thread-safe.

    Returns {"ok": bool, "error"?: str}. The resume is only SCHEDULED here (the
    caller must not assert the run has advanced on the immediately-following poll).
    """
    h = RUNS.get(run_id)
    if h is None:
        return {"ok": False, "error": "unknown run_id"}
    fut = h.approval_future
    if fut is None or fut.done():
        return {"ok": False, "error": f"run is not awaiting approval (status={h.status})"}
    payload = {"decision": decision, "targets": targets or [], "reason": reason}
    # Schedule set_result on the loop that owns the future — correct even if this
    # is ever invoked off-loop (sync route / threadpool).
    h.loop.call_soon_threadsafe(_safe_set_result, fut, payload)
    return {"ok": True}


def _safe_set_result(fut: asyncio.Future, payload: dict[str, Any]) -> None:
    if not fut.done():
        fut.set_result(payload)


def sweep_orphans() -> list[dict[str, Any]]:
    """On startup, find persisted runs stuck mid-flight with no live handle here
    and mark them orphaned (the UI offers a one-click re-trigger). Returns them."""
    orphans = store.find_active_orphans(set(RUNS))
    for o in orphans:
        store.set_state(o["run_id"], {"status": "orphaned"})
    return orphans
