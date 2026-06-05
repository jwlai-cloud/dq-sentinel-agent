"""Orchestration tests for the 7-step loop (spec `agent-loop`).

Fully mocked: no Fivetran network, no Gemini call, no BQ, no writes. Patches the
loop's step boundaries to exercise control flow + the structural gate against the
spec scenarios:
  - baseline missing terminates before inspect/diagnose/act
  - no-issue scan skips diagnose/act/verify
  - approved resync_tables -> ACT executes the right write tool -> VERIFY passed
  - modified targets flow through to ACT
  - reject -> one revised diagnosis -> second reject -> unresolved (no write)
  - manual action -> no write, VERIFY still re-checks
  - invalid proposal x3 -> diagnosis_failed
  - poll timeout -> unresolved

Run: uv run scripts/test_loop.py   (no credentials needed)
"""
from __future__ import annotations

import asyncio
import json

from dq_sentinel import act, loop


# --- canned fixtures -------------------------------------------------------
DETAILS = {
    "schema": "dq_sentinel.loan_products",
    "service": "google_sheets",
    "succeeded_at": "2026-06-02T08:00:00Z",
    "failed_at": None,
    "status": {"setup_state": "connected", "sync_state": "scheduled", "warnings": []},
}

DRIFT_CHECKS = [
    {"check_name": "schema_mismatch", "table": "loan_products", "column": None,
     "current_value": ["headline_apr"], "baseline_value": ["base_apr"],
     "deviation": {"added": ["headline_apr"], "removed": ["base_apr"]}, "passed": False, "severity": "MEDIUM"},
    {"check_name": "null_rate", "table": "loan_products", "column": "base_apr",
     "current_value": 1.0, "baseline_value": 0.0, "deviation": 1.0, "passed": False, "severity": "HIGH"},
]
CLEAN_CHECKS = [
    {"check_name": "row_count", "table": "loan_products", "column": None,
     "current_value": 100, "baseline_value": 100, "deviation": 0.0, "passed": True, "severity": "OK"},
]

GOOD_PROPOSAL = {
    "root_cause": "source column base_apr renamed to headline_apr",
    "severity": "HIGH", "evidence": ["schema diff", "null spike"],
    "action": "resync_tables", "targets": ["loan_products"],
    "reasoning": "backfill the renamed column", "manual_instructions": "",
}
MANUAL_PROPOSAL = {**GOOD_PROPOSAL, "action": "manual", "targets": [],
                   "manual_instructions": "revert the sheet header"}


# --- patch helpers ---------------------------------------------------------
def install(monkey: dict):
    """Apply a dict of {dotted_target: value} patches; return an undo fn."""
    saved = []
    for target, value in monkey.items():
        obj = loop
        *mods, attr = target.split(".")
        for m in mods:
            obj = getattr(obj, m)
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def undo():
        for obj, attr, old in saved:
            setattr(obj, attr, old)

    return undo


async def _afn(value):
    return value


def base_patches(*, has_baseline=True, checks=DRIFT_CHECKS, details=DETAILS):
    return {
        "connection_details": lambda cid: _afn(dict(details)),
        "connection_tables": lambda cid: _afn(("dq_sentinel", ["loan_products"])),
        "_has_baseline": lambda t: has_baseline,
        "inspect_table": lambda t: list(checks),
    }


async def auto_approve(proposal, planned):
    return {"decision": "approved"}


async def auto_reject(proposal, planned):
    return {"decision": "rejected", "reason": "false positive"}


# --- assertions ------------------------------------------------------------
PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail and not cond else ""))


# --- scenarios -------------------------------------------------------------
async def scenario_baseline_missing():
    print("\n# baseline missing -> terminate")
    undo = install(base_patches(has_baseline=False))
    try:
        r = await loop.run_loop("c", approval=auto_approve)
    finally:
        undo()
    check("status == baseline_missing", r["status"] == "baseline_missing", r["status"])
    check("no action taken", r["action_taken"] is None)


async def scenario_no_issue():
    print("\n# clean data -> no-issue, skip diagnose/act/verify")
    undo = install(base_patches(checks=CLEAN_CHECKS))
    try:
        r = await loop.run_loop("c", approval=auto_approve)
    finally:
        undo()
    check("status == no-issue", r["status"] == "no-issue", r["status"])
    check("no remediation proposed", r["remediation_proposed"] is None)


async def scenario_happy_resync():
    print("\n# drift -> approve resync_tables -> ACT -> VERIFY passed")
    acted = {}

    async def fake_act(proposal, cid):
        acted["proposal"] = proposal
        acted["plan"] = act.planned_call(proposal, cid)
        return {"executed": True, "action": proposal["action"], "tool": "resync_tables",
                "connection_id": cid, "targets": proposal["targets"]}

    async def fake_verify(cid, failed, **kw):
        return {"verification_result": "passed", "sync_wait_seconds": 42.0, "polls": 2,
                "before_after": [{"check_name": "null_rate", "before_passed": False, "after_passed": True}]}

    patches = base_patches()
    patches.update({
        "diagnose": lambda p, feedback=None: _afn(dict(GOOD_PROPOSAL)),
        "act.act": fake_act,
        "verify.verify": fake_verify,
    })
    undo = install(patches)
    try:
        r = await loop.run_loop("subjected_synthesis", approval=auto_approve, poll_interval=0.01)
    finally:
        undo()
    check("status == resolved", r["status"] == "resolved", r["status"])
    check("verification == passed", r["verification_result"] == "passed")
    check("ACT got resync_tables", acted["proposal"]["action"] == "resync_tables")
    plan = acted["plan"]
    check("planned tool == resync_tables", plan["tool"] == "resync_tables", str(plan))
    body = json.loads(plan["arguments"]["request_body"])
    check("request_body schema == [loan_products]", body == {"schema": ["loan_products"]}, str(body))
    check("TTR splits sync_wait", r["time_to_resolution"]["sync_wait_seconds"] == 42.0,
          str(r["time_to_resolution"]))


async def scenario_modified_targets():
    print("\n# approve with modified targets -> ACT uses edited targets")
    acted = {}

    async def fake_act(proposal, cid):
        acted["targets"] = proposal["targets"]
        return {"executed": True, "action": proposal["action"], "tool": "resync_tables",
                "connection_id": cid, "targets": proposal["targets"]}

    async def approve_modified(proposal, planned):
        return {"decision": "modified", "targets": ["loan_products", "extra"]}

    patches = base_patches()
    patches.update({
        "diagnose": lambda p, feedback=None: _afn(dict(GOOD_PROPOSAL)),
        "act.act": fake_act,
        "verify.verify": lambda *a, **k: _afn({"verification_result": "passed", "sync_wait_seconds": 0.0, "polls": 0, "before_after": []}),
    })
    undo = install(patches)
    try:
        r = await loop.run_loop("c", approval=approve_modified, poll_interval=0.01)
    finally:
        undo()
    check("ACT used edited targets", acted.get("targets") == ["loan_products", "extra"], str(acted))
    check("approval recorded approved", r["approval_decision"]["decision"] == "approved")


async def scenario_reject_twice():
    print("\n# reject -> revised diagnosis -> reject again -> unresolved, no write")
    write_called = {"n": 0}

    async def counting_act(proposal, cid):
        write_called["n"] += 1
        return {"executed": True}

    patches = base_patches()
    patches.update({
        "diagnose": lambda p, feedback=None: _afn(dict(GOOD_PROPOSAL)),
        "act.act": counting_act,
        "verify.verify": lambda *a, **k: _afn({"verification_result": "passed"}),
    })
    undo = install(patches)
    try:
        r = await loop.run_loop("c", approval=auto_reject, poll_interval=0.01)
    finally:
        undo()
    check("status == unresolved", r["status"] == "unresolved", r["status"])
    check("NO write tool invoked", write_called["n"] == 0, f"act called {write_called['n']}x")
    check("approval recorded rejected", r["approval_decision"]["decision"] == "rejected")


async def scenario_manual():
    print("\n# manual action -> no write, VERIFY still re-checks")
    async def fake_verify(cid, failed, *, executed_write, **kw):
        check("verify told executed_write=False", executed_write is False)
        return {"verification_result": "failed", "sync_wait_seconds": 0.0, "polls": 0, "before_after": []}

    patches = base_patches()
    patches.update({
        "diagnose": lambda p, feedback=None: _afn(dict(MANUAL_PROPOSAL)),
        "verify.verify": fake_verify,
    })
    undo = install(patches)
    try:
        r = await loop.run_loop("c", approval=auto_approve, poll_interval=0.01)
    finally:
        undo()
    check("manual ACT not executed", r["action_taken"]["executed"] is False, str(r["action_taken"]))


async def scenario_diagnosis_failed():
    print("\n# invalid proposal x3 -> diagnosis_failed")
    bad = {**GOOD_PROPOSAL, "action": "resync_tables", "targets": []}  # invalid: resync needs targets
    patches = base_patches()
    patches.update({"diagnose": lambda p, feedback=None: _afn(dict(bad))})
    undo = install(patches)
    try:
        r = await loop.run_loop("c", approval=auto_approve)
    finally:
        undo()
    check("status == diagnosis_failed", r["status"] == "diagnosis_failed", r["status"])
    check("verification == diagnosis_failed", r["verification_result"] == "diagnosis_failed")


async def scenario_timeout():
    print("\n# poll timeout -> unresolved")
    patches = base_patches()
    patches.update({
        "diagnose": lambda p, feedback=None: _afn(dict(GOOD_PROPOSAL)),
        "act.act": lambda proposal, cid: _afn({"executed": True, "action": "resync_tables", "tool": "resync_tables", "connection_id": cid, "targets": proposal["targets"]}),
        "verify.verify": lambda *a, **k: _afn({"verification_result": "timed_out", "sync_wait_seconds": 1800.0, "polls": 60, "before_after": []}),
    })
    undo = install(patches)
    try:
        r = await loop.run_loop("c", approval=auto_approve, poll_interval=0.01)
    finally:
        undo()
    check("status == unresolved", r["status"] == "unresolved", r["status"])
    check("verification == timed_out", r["verification_result"] == "timed_out")


# --- pure ACT planning (no patching) ---------------------------------------
def scenario_act_planning():
    print("\n# ACT planned_call body shapes (pure)")
    cases = {
        "sync_connection": ({}, {}),
        "resync_connection": ({}, {}),
        "resync_tables": ({"targets": ["loan_products"]}, {"schema": ["loan_products"]}),
        "reload_schema": ({}, {"exclude_mode": "PRESERVE"}),
    }
    for action, (extra, want_body) in cases.items():
        p = {**GOOD_PROPOSAL, "action": action, "targets": extra.get("targets", [])}
        plan = act.planned_call(p, "cid")
        tool = act.ACTION_TO_TOOL[action]
        body = json.loads(plan["arguments"]["request_body"])
        check(f"{action} -> {tool} body {want_body}", plan["tool"] == tool and body == want_body, f"got {plan['tool']} {body}")
    manual = act.planned_call(MANUAL_PROPOSAL, "cid")
    check("manual -> no tool", manual["tool"] is None and manual["manual_instructions"] == "revert the sheet header")


async def main() -> int:
    await scenario_baseline_missing()
    await scenario_no_issue()
    await scenario_happy_resync()
    await scenario_modified_targets()
    await scenario_reject_twice()
    await scenario_manual()
    await scenario_diagnosis_failed()
    await scenario_timeout()
    scenario_act_planning()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n==== {passed}/{total} checks passed ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
