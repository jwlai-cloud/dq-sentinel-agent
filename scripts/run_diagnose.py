"""Demo the DIAGNOSE step on the live loan_products schema-drift incident.

Builds a real evidence payload from the BQ DQ checks (section 4) + a short
Fivetran status stub, runs the diagnosis agent, and prints the structured
propose_remediation proposal. Validates it against the spec.

Run:
    export GOOGLE_APPLICATION_CREDENTIALS=.secrets/dq-sentinel-runtime.json
    export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=agent-era GOOGLE_CLOUD_LOCATION=global
    uv run scripts/run_diagnose.py
"""
from __future__ import annotations

import asyncio
import json

from dq_sentinel import bq
from dq_sentinel.diagnose import diagnose, validate_payload


async def main() -> int:
    # INSPECT: gather real failed checks on the drifted table.
    failed = [
        bq.dq_check_schema_mismatch("loan_products"),
        bq.dq_check_null_rate("loan_products", "base_apr"),
    ]
    payload = {
        "connection": {
            "id": "subjected_synthesis",
            "schema": "dq_sentinel.loan_products",
            "service": "google_sheets",
            "status": {"setup_state": "connected", "sync_state": "scheduled"},
        },
        "table": "loan_products",
        "failed_checks": failed,
    }
    print("=== evidence payload ===")
    print(json.dumps(payload, indent=2, default=str))

    print("\n=== running diagnosis (Gemini) ===")
    proposal = await diagnose(payload)
    if proposal is None:
        print("FAIL: model did not call propose_remediation")
        return 1

    print("\n=== structured proposal ===")
    print(json.dumps(proposal, indent=2, default=str))

    errs = validate_payload(proposal)
    print(f"\nvalidation: {'PASS' if not errs else 'FAIL ' + str(errs)}")
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
