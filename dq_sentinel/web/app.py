"""FastAPI app for DQ Sentinel. Uvicorn entrypoint: `dq_sentinel.web.app:app`.

One async process. Runs (run_loop) are detached asyncio tasks on this event loop;
the approval gate is bridged with an asyncio.Future (web/runs.py). A background
heartbeat advances a counter so /healthz can prove Cloud Run background CPU is
allocated (--no-cpu-throttling) — if the beat stalls between requests, the
detached ACT/VERIFY task would silently freeze too.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dq_sentinel.web import runs
from dq_sentinel.web.api import router as api_router
from dq_sentinel.web.views import router as views_router

log = logging.getLogger("dq_sentinel.web")

_HEARTBEAT: dict[str, Any] = {"beats": 0, "last_beat_ts": 0.0, "started_ts": 0.0}


async def _heartbeat() -> None:
    _HEARTBEAT["started_ts"] = time.time()
    while True:
        _HEARTBEAT["beats"] += 1
        _HEARTBEAT["last_beat_ts"] = time.time()
        await asyncio.sleep(10)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    orphans = runs.sweep_orphans()
    if orphans:
        log.warning("startup orphan-sweep marked %d stuck run(s) for re-trigger", len(orphans))
    task = asyncio.create_task(_heartbeat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="DQ Sentinel", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(views_router)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    now = time.time()
    last = _HEARTBEAT["last_beat_ts"]
    # background CPU is healthy if the beat advanced within ~3 intervals
    healthy = last > 0 and (now - last) < 35
    return {
        "ok": healthy,
        "beats": _HEARTBEAT["beats"],
        "seconds_since_beat": round(now - last, 1) if last else None,
        "active_runs": len(runs.RUNS),
    }
