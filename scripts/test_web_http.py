"""HTTP-level test of the web layer: real FastAPI app via TestClient, mocked loop.

Drives the exact request sequence the browser makes — POST /api/runs, poll
GET /api/runs/{id}, POST /api/runs/{id}/decision — and asserts the gate holds
over HTTP: no write fires until the decision route resolves the Future with
"approved", and the incident lands in history. No credentials, no network.

Run: uv run scripts/test_web_http.py
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from dq_sentinel import loop

GOOD = {
    "root_cause": "base_apr renamed to headline_apr", "severity": "HIGH",
    "evidence": ["schema diff: base_apr removed, headline_apr added", "null_rate base_apr 0%->100%"],
    "action": "resync_tables", "targets": ["loan_products"], "reasoning": "backfill", "manual_instructions": "",
}
DETAILS = {"schema": "dq_sentinel.loan_products", "service": "google_sheets",
           "succeeded_at": "2026-06-02T08:00:00Z", "failed_at": None,
           "status": {"setup_state": "connected", "sync_state": "scheduled", "warnings": []}}
DRIFT = [{"check_name": "null_rate", "table": "loan_products", "column": "base_apr",
          "current_value": 1.0, "baseline_value": 0.0, "deviation": 1.0, "passed": False, "severity": "HIGH"}]

results: list[tuple[str, bool, str]] = []
acts: list[dict] = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def install():
    async def fake_act(proposal, cid):
        acts.append({"targets": list(proposal.get("targets") or [])})
        return {"executed": True, "action": proposal["action"], "tool": "resync_tables",
                "connection_id": cid, "targets": proposal["targets"]}

    async def fake_verify(cid, failed, **kw):
        return {"verification_result": "passed", "sync_wait_seconds": 1.0, "polls": 1,
                "before_after": [{"check_name": "null_rate", "table": "loan_products", "column": "base_apr",
                                  "before_value": 1.0, "after_value": 0.0, "before_passed": False, "after_passed": True}]}

    async def afn(v):
        return v

    patches = {
        "connection_details": lambda cid: afn(dict(DETAILS)),
        "connection_tables": lambda cid: afn(("dq_sentinel", ["loan_products"])),
        "_has_baseline": lambda t: True,
        "inspect_table": lambda t: list(DRIFT),
        "diagnose": lambda p, feedback=None: afn(dict(GOOD)),
        "act.act": fake_act,
        "verify.verify": fake_verify,
    }
    saved = []
    for target, value in patches.items():
        obj = loop
        *mods, attr = target.split(".")
        for m in mods:
            obj = getattr(obj, m)
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)
    return lambda: [setattr(o, a, old) for o, a, old in saved]


def poll_until(client, rid, pred, timeout=5.0):
    t0 = time.time()
    snap = {}
    while time.time() - t0 < timeout:
        snap = client.get(f"/api/runs/{rid}").json()
        if pred(snap):
            return snap
        time.sleep(0.05)
    return snap


def main() -> int:
    undo = install()
    # import app AFTER patching so its imports bind the patched loop module
    from dq_sentinel.web.app import app
    try:
        with TestClient(app) as client:
            print("\n# infra routes")
            check("GET / -> 200 html", client.get("/").status_code == 200)
            hz = client.get("/api/health").json()
            check("GET /api/health ok", hz.get("ok") is True, str(hz))
            conns = client.get("/api/connections").json()
            check("GET /api/connections graceful (no creds)", "connections" in conns, str(conns)[:120])

            print("\n# happy path over HTTP: start -> gate -> approve -> resolved")
            r = client.post("/api/runs", json={"connection_id": "cid_http"})
            check("POST /api/runs -> 202", r.status_code == 202, str(r.status_code))
            rid = r.json()["run_id"]

            snap = poll_until(client, rid, lambda s: s.get("awaiting_decision"))
            check("reached gate (awaiting_decision)", snap.get("awaiting_decision") is True, snap.get("status"))
            check("NO write before approval", len(acts) == 0, f"acts={len(acts)}")
            check("proposal in snapshot", (snap.get("proposal") or {}).get("action") == "resync_tables")
            check("planned_call MCP preview present",
                  (snap.get("planned_call") or {}).get("tool") == "resync_tables", str(snap.get("planned_call")))

            d = client.post(f"/api/runs/{rid}/decision", json={"decision": "approved", "targets": [], "reason": ""})
            check("POST /decision -> 200", d.status_code == 200, str(d.status_code))
            dup = client.post(f"/api/runs/{rid}/decision", json={"decision": "approved"})
            check("duplicate decision -> 409", dup.status_code == 409, str(dup.status_code))

            snap = poll_until(client, rid, lambda s: s.get("status") in ("resolved", "unresolved", "error"))
            check("status resolved", snap.get("status") == "resolved", snap.get("status"))
            check("write fired once after approval", len(acts) == 1, f"acts={len(acts)}")
            check("report has before/after", bool((snap.get("report") or {}).get("after_metrics")))

            hist = client.get("/api/runs").json()
            check("incident in history", any(i.get("status") == "resolved" for i in hist["incidents"]), str(len(hist["incidents"])))

            print("\n# decision guards over HTTP")
            check("decision on unknown run -> 409", client.post("/api/runs/nope/decision",
                  json={"decision": "approved"}).status_code == 409)
            check("invalid decision -> 400", client.post(f"/api/runs/{rid}/decision",
                  json={"decision": "frobnicate"}).status_code == 400)
    finally:
        undo()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n==== {passed}/{total} checks passed ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
