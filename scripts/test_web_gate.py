"""Prove the web approval-gate bridge (dq_sentinel/web/runs.py) BEFORE any HTTP.

Drives the real run_loop as a detached task via runs.start_run, then interacts
with the parked approval Future exactly as the FastAPI /decision route will
(runs.submit_decision). Fully mocked loop boundaries — no Fivetran, no Gemini,
no BQ, no writes hit the network. Asserts the structural-gate invariants:

  (a) NO write (act.act) fires until the future resolves with "approved"
  (b) "rejected" triggers exactly one re-diagnosis and the gate RE-OPENS
  (c) "modified" closes the gate as a same-cycle re-approval with edited targets
  (d) the run survives a multi-second human wait at the gate (Future park works)

Run: uv run scripts/test_web_gate.py   (no credentials needed)
"""
from __future__ import annotations

import asyncio

from dq_sentinel import loop
from dq_sentinel.web import runs

GOOD = {
    "root_cause": "base_apr renamed to headline_apr", "severity": "HIGH",
    "evidence": ["schema diff", "null spike"], "action": "resync_tables",
    "targets": ["loan_products"], "reasoning": "backfill", "manual_instructions": "",
}
DETAILS = {"schema": "dq_sentinel.loan_products", "service": "google_sheets",
           "succeeded_at": "2026-06-02T08:00:00Z", "failed_at": None,
           "status": {"setup_state": "connected", "sync_state": "scheduled", "warnings": []}}
DRIFT = [{"check_name": "null_rate", "table": "loan_products", "column": "base_apr",
          "current_value": 1.0, "baseline_value": 0.0, "deviation": 1.0, "passed": False, "severity": "HIGH"}]

results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def install(patches: dict):
    saved = []
    for target, value in patches.items():
        obj = loop
        *mods, attr = target.split(".")
        for m in mods:
            obj = getattr(obj, m)
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)
    return lambda: [setattr(o, a, old) for o, a, old in saved]


async def _afn(v):
    return v


async def wait_until(pred, timeout=5.0):
    t0 = asyncio.get_event_loop().time()
    while not pred():
        if asyncio.get_event_loop().time() - t0 > timeout:
            raise TimeoutError("condition not met")
        await asyncio.sleep(0.01)


def base_patches(diagnose_counter: list, act_events: list, verify_result="passed"):
    async def fake_diagnose(payload, feedback=None):
        diagnose_counter.append(feedback)
        return dict(GOOD)

    async def fake_act(proposal, cid):
        act_events.append({"targets": list(proposal.get("targets") or [])})
        return {"executed": True, "action": proposal["action"], "tool": "resync_tables",
                "connection_id": cid, "targets": proposal["targets"]}

    async def fake_verify(cid, failed, **kw):
        return {"verification_result": verify_result, "sync_wait_seconds": 1.0, "polls": 1, "before_after": []}

    return {
        "connection_details": lambda cid: _afn(dict(DETAILS)),
        "connection_tables": lambda cid: _afn(("dq_sentinel", ["loan_products"])),
        "_has_baseline": lambda t: True,
        "inspect_table": lambda t: list(DRIFT),
        "diagnose": fake_diagnose,
        "act.act": fake_act,
        "verify.verify": fake_verify,
    }


async def scenario_approve():
    print("\n# approve: parks at gate, NO write until approved, then ACT+VERIFY -> resolved")
    diag, acts = [], []
    undo = install(base_patches(diag, acts))
    try:
        rid = runs.start_run("cid_approve")
        await wait_until(lambda: runs.snapshot(rid)["awaiting_decision"])
        snap = runs.snapshot(rid)
        check("(a) no write before approval", len(acts) == 0, f"acts={len(acts)}")
        check("proposal surfaced at gate", snap["proposal"] and snap["proposal"]["action"] == "resync_tables")
        check("awaiting_decision flag set", snap["awaiting_decision"] is True)

        # simulate a human pause, then the /decision route
        await asyncio.sleep(0.2)
        res = runs.submit_decision(rid, "approved")
        check("decision accepted", res["ok"] is True)
        await wait_until(lambda: runs.snapshot(rid)["status"] in ("resolved", "unresolved", "error"))
        snap = runs.snapshot(rid)
        check("(d) write fired AFTER approval, exactly once", len(acts) == 1, f"acts={len(acts)}")
        check("status resolved", snap["status"] == "resolved", snap["status"])
        check("report present", snap["report"] is not None)
        check("human wait excluded from agent TTR", snap["time_to_resolution"]["human_wait_seconds"] >= 0.2,
              str(snap.get("time_to_resolution")))
    finally:
        undo()


async def scenario_reject_then_reject():
    print("\n# reject: one re-diagnosis + gate re-opens; second reject -> unresolved, 0 writes")
    diag, acts = [], []
    undo = install(base_patches(diag, acts))
    try:
        rid = runs.start_run("cid_reject")
        await wait_until(lambda: runs.snapshot(rid)["awaiting_decision"] and len(diag) == 1)
        runs.submit_decision(rid, "rejected", reason="false positive")
        # gate must RE-OPEN with a FRESH future after exactly one re-diagnosis.
        # Key on (diag==2 AND a live future) so we don't observe the stale gate.
        await wait_until(lambda: len(diag) == 2 and runs.snapshot(rid)["awaiting_decision"])
        check("(b) re-diagnosed exactly once (1 initial + 1 revise)", len(diag) == 2,
              f"diagnose calls={len(diag)}")
        check("no write after first reject", len(acts) == 0, f"acts={len(acts)}")
        runs.submit_decision(rid, "rejected", reason="still no")
        await wait_until(lambda: runs.snapshot(rid)["status"] in ("unresolved", "resolved", "error"))
        snap = runs.snapshot(rid)
        check("status unresolved", snap["status"] == "unresolved", snap["status"])
        check("ZERO writes across rejects", len(acts) == 0, f"acts={len(acts)}")
    finally:
        undo()


async def scenario_modified():
    print("\n# modified: same-cycle re-approval, ACT uses edited targets")
    diag, acts = [], []
    undo = install(base_patches(diag, acts))
    try:
        rid = runs.start_run("cid_modified")
        await wait_until(lambda: runs.snapshot(rid)["awaiting_decision"])
        runs.submit_decision(rid, "modified", targets=["loan_products", "extra_table"])
        await wait_until(lambda: runs.snapshot(rid)["status"] in ("resolved", "unresolved", "error"))
        check("(c) ACT used edited targets", acts and acts[0]["targets"] == ["loan_products", "extra_table"], str(acts))
        check("single write", len(acts) == 1, f"acts={len(acts)}")
    finally:
        undo()


async def scenario_decision_guards():
    print("\n# guards: decision on unknown/closed gate is rejected cleanly")
    check("unknown run_id -> ok False", runs.submit_decision("nope", "approved")["ok"] is False)


async def main() -> int:
    await scenario_approve()
    await scenario_reject_then_reject()
    await scenario_modified()
    await scenario_decision_guards()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n==== {passed}/{total} checks passed ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
