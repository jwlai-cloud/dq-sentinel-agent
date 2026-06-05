"""JSON job-API for the DQ Sentinel web layer.

Four routes drive the whole UI; the browser is a pure polling client.
  POST /api/runs                 -> 202 {run_id}   (start a detached run)
  GET  /api/runs/{run_id}        -> run snapshot    (poll: status/proposal/report)
  POST /api/runs/{run_id}/decision -> {ok}          (resolve the approval gate)
  GET  /api/runs                 -> incident history
  GET  /api/connections          -> Fivetran connections (the run picker)

The decision route is async (runs on the serving event loop) so resolving the
approval Future is correct; see runs.submit_decision.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dq_sentinel import loop as agent_loop
from dq_sentinel.web import runs, store

router = APIRouter(prefix="/api")


class StartRunReq(BaseModel):
    connection_id: str


class DecisionReq(BaseModel):
    decision: str  # approved | rejected | modified
    targets: list[str] | None = None
    reason: str = ""


@router.post("/runs", status_code=202)
async def start_run(req: StartRunReq) -> dict[str, Any]:
    if not req.connection_id:
        raise HTTPException(400, "connection_id required")
    run_id = runs.start_run(req.connection_id)
    return {"run_id": run_id, "status": "detecting"}


@router.get("/runs")
async def history() -> dict[str, Any]:
    return {"incidents": store.list_history()}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    snap = runs.snapshot(run_id)
    if snap is None:
        raise HTTPException(404, "unknown run_id")
    return snap


@router.post("/runs/{run_id}/decision")
async def decide(run_id: str, req: DecisionReq) -> dict[str, Any]:
    if req.decision not in ("approved", "rejected", "modified"):
        raise HTTPException(400, f"invalid decision {req.decision!r}")
    res = runs.submit_decision(run_id, req.decision, req.targets, req.reason)
    if not res["ok"]:
        raise HTTPException(409, res["error"])
    return res


@router.get("/connections")
async def connections() -> dict[str, Any]:
    """SCAN list_connections for the run picker. Returns [] + error on failure
    (e.g. no Fivetran creds in local dev) rather than 500ing the page."""
    try:
        items = await agent_loop.scan_all()
    except Exception as exc:  # noqa: BLE001
        return {"connections": [], "error": f"{type(exc).__name__}: {exc}"}
    out = []
    for c in items:
        status = c.get("status", {}) or {}
        out.append({
            "id": c.get("id"),
            "schema": c.get("schema"),
            "service": c.get("service"),
            "sync_state": status.get("sync_state"),
            "setup_state": status.get("setup_state"),
        })
    return {"connections": out}
