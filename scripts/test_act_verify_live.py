"""LIVE non-destructive test of step 6 ACT + step 7 VERIFY mechanics.

Fires a real `sync_connection` (on-demand sync, body {}) on a CLEAN connection
and watches the verify poll loop detect completion via get_connection_details.
This is NOT a resync/reload — it only re-reads the same clean sheet, so no data
or schema changes. Proves: write-enabled MCP invocation + poll-until-synced.

Target defaults to the account_holders connection (auto-discovered by schema).

Run:
    export FIVETRAN_API_KEY=$(gcloud secrets versions access latest --secret=FIVETRAN_API_KEY --project=agent-era --account=junwei.lai@gmail.com)
    export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest --secret=FIVETRAN_API_SECRET --project=agent-era --account=junwei.lai@gmail.com)
    uv run scripts/test_act_verify_live.py
"""
from __future__ import annotations

import asyncio
import json

from dq_sentinel import act, loop, verify

TARGET_SCHEMA_SUBSTR = "account_holders"


async def find_connection() -> str | None:
    for c in await loop.scan_all():
        schema = (c.get("schema") or "") + " " + (c.get("id") or "")
        if TARGET_SCHEMA_SUBSTR in schema:
            return c["id"]
    return None


async def main() -> int:
    cid = await find_connection()
    if not cid:
        print(f"FAIL: no connection matching {TARGET_SCHEMA_SUBSTR!r}")
        return 1
    print(f"target connection: {cid}")

    # pre-ACT sync markers
    pre = await loop.connection_details(cid)
    pre_succeeded = pre.get("succeeded_at")
    pre_failed = pre.get("failed_at")
    print(f"pre  succeeded_at={pre_succeeded} sync_state={pre.get('status',{}).get('sync_state')}")

    # STEP 6 ACT — approved sync_connection proposal
    proposal = {
        "root_cause": "live mechanics test", "severity": "LOW", "evidence": ["n/a"],
        "action": "sync_connection", "targets": [], "reasoning": "trigger on-demand sync",
        "manual_instructions": "",
    }
    plan = act.planned_call(proposal, cid)
    print(f"ACT plan: {plan['tool']}({json.dumps(plan['arguments'])})")
    act_result = await act.act(proposal, cid)
    print(f"ACT result: executed={act_result['executed']} is_error={act_result.get('is_error')}")
    print(f"  response: {json.dumps(act_result.get('response'), default=str)[:300]}")
    if not act_result["executed"]:
        print("FAIL: write did not execute")
        return 1

    # STEP 7 VERIFY — no failed checks on a clean connection; just prove the poll
    print("VERIFY: polling get_connection_details until sync completes (15s interval, 10m cap)...")
    v = await verify.verify(
        cid, [], executed_write=True,
        baseline_succeeded_at=pre_succeeded, baseline_failed_at=pre_failed,
        interval=15, timeout=600,
    )
    print(json.dumps(v, indent=2, default=str))
    ok = v["verification_result"] == "passed"
    print(f"\n{'PASS' if ok else 'RESULT=' + v['verification_result']}: "
          f"sync_wait={v.get('sync_wait_seconds')}s polls={v.get('polls')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
