"""Drive the full 7-step loop against a live Fivetran connection.

Approval (step 5) is interactive by default. Set DQ_APPROVAL to run
non-interactively:
  DQ_APPROVAL=reject  -> reject at the gate (safe: NO Fivetran write fires)
  DQ_APPROVAL=approve -> approve and execute the write + verify (LIVE write!)

Run (read-only end-to-end up to the gate, no write):
    export GOOGLE_APPLICATION_CREDENTIALS=.secrets/dq-sentinel-runtime.json
    export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=agent-era GOOGLE_CLOUD_LOCATION=global
    export FIVETRAN_API_KEY=$(gcloud secrets versions access latest --secret=FIVETRAN_API_KEY --project=agent-era)
    export FIVETRAN_API_SECRET=$(gcloud secrets versions access latest --secret=FIVETRAN_API_SECRET --project=agent-era)
    DQ_APPROVAL=reject uv run scripts/run_loop.py subjected_synthesis
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dq_sentinel import loop

DEFAULT_CONNECTION = "subjected_synthesis"  # loan_products (drift fixture)


async def approval(proposal: dict, planned: dict) -> dict:
    print("\n========== STEP 5: APPROVAL GATE ==========")
    print(f"  severity   : {proposal.get('severity')}")
    print(f"  root cause : {proposal.get('root_cause')}")
    print(f"  action     : {proposal.get('action')}  targets={proposal.get('targets')}")
    print("  evidence   :")
    for e in proposal.get("evidence", []):
        print(f"    - {e}")
    if planned.get("tool"):
        print(f"  WOULD EXECUTE: {planned['tool']}({json.dumps(planned['arguments'])})")
    else:
        print(f"  MANUAL: {planned.get('manual_instructions')}")

    forced = os.environ.get("DQ_APPROVAL")
    if forced:
        print(f"  [non-interactive] DQ_APPROVAL={forced}")
        if forced == "approve":
            return {"decision": "approved"}
        return {"decision": "rejected", "reason": "non-interactive reject"}

    ans = input("  approve / reject / modify <t1,t2>: ").strip()
    if ans.startswith("modify"):
        targets = [t.strip() for t in ans.split(maxsplit=1)[1].split(",")] if " " in ans else []
        return {"decision": "modified", "targets": targets}
    if ans == "approve":
        return {"decision": "approved"}
    return {"decision": "rejected", "reason": ans or "rejected"}


async def main() -> int:
    cid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONNECTION
    print(f"Running 7-step loop on connection {cid!r} ...")
    report = await loop.run_loop(cid, approval=approval, poll_interval=15, poll_timeout=1800)
    print("\n========== INCIDENT REPORT ==========")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
