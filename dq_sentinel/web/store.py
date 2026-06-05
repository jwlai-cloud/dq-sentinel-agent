"""Durable run state for the web layer.

MVP uses an in-memory store (correct under the single pinned Cloud Run instance
the deploy enforces). Firestore is the P1 upgrade for cross-restart incident
history + crash forensics; this module isolates that choice behind one interface
so swapping in `google-cloud-firestore` is a single-file change.

Two concerns, deliberately separate:
  - run state (live, one row per run_id) — the source of truth while a run is in
    flight is the in-process RunHandle (runs.py); the store is the durable mirror.
  - incident history — the append-only log of completed reports for the dashboard.
"""
from __future__ import annotations

import threading
from typing import Any

# stage -> run_id -> latest partial state dict
_STATE: dict[str, dict[str, Any]] = {}
_HISTORY: list[dict[str, Any]] = []
_LOCK = threading.Lock()


def set_state(run_id: str, partial: dict[str, Any]) -> None:
    """Merge a partial state update for a run (durable mirror of RunHandle)."""
    with _LOCK:
        _STATE.setdefault(run_id, {"run_id": run_id}).update(partial)


def get_state(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        s = _STATE.get(run_id)
        return dict(s) if s else None


def append_history(report: dict[str, Any]) -> None:
    """Record a completed incident report for the history view."""
    with _LOCK:
        _HISTORY.append(dict(report))


def list_history(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(r) for r in _HISTORY[-limit:][::-1]]


def find_active_orphans(live_run_ids: set[str]) -> list[dict[str, Any]]:
    """Persisted runs stuck mid-flight with no live RunHandle in this process.

    On a fresh instance (restart / instance hop) these would otherwise await
    forever; the caller surfaces them as one-click re-triggers.
    """
    active = {"detecting", "inspecting", "diagnosing", "awaiting_approval",
              "rediagnosing", "acting", "verifying"}
    with _LOCK:
        return [
            dict(s) for rid, s in _STATE.items()
            if s.get("status") in active and rid not in live_run_ids
        ]
