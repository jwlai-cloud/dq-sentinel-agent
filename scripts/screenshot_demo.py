"""Capture demo screenshots of the LIVE hosted DQ Sentinel UI WITHOUT any write.

Loads the hosted page (GET-only: the connection list is a read-only scan), then
paints the approval-gate and resolved-report states by injecting the REAL data
from the already-proven loosen_signal run into the app's own render() function.
No Fivetran write is triggered. Uses system Chrome (no chromium download).

Run: uv run --with playwright python scripts/screenshot_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://dq-sentinel-sjsibsau7a-uc.a.run.app"
OUT = Path(__file__).resolve().parents[1] / "docs" / "demo" / "img"
OUT.mkdir(parents=True, exist_ok=True)

# --- REAL data from the proven run (loosen_signal / account_holders) ---------
PROPOSAL = {
    "severity": "MEDIUM",
    "root_cause": ("The 'account_holders' table has become stale with a freshness value of 4541 "
                   "compared to the 180 baseline, despite the connection 'loosen_signal' being "
                   "active and on-schedule."),
    "evidence": [
        "The freshness check for table 'account_holders' failed with a current value of 4541, exceeding the baseline value of 180.",
        "The Fivetran connection 'loosen_signal' is healthy (setup_state: connected, sync_state: scheduled, update_state: on_schedule) with no hard sync failures.",
    ],
    "action": "resync_connection",
    "targets": ["account_holders"],
}
PLANNED = {"tool": "resync_connection",
           "arguments": {"connection_id": "loosen_signal", "request_body": "{}"}}
PROGRESS = [
    {"stage": "scanning", "detail": {"connection_id": "loosen_signal"}, "ts": 1000},
    {"stage": "detecting", "detail": {"fivetran_issues": 0}, "ts": 1002},
    {"stage": "inspecting", "detail": {"tables": ["account_holders"]}, "ts": 1004},
    {"stage": "diagnosing", "detail": {"table": "account_holders", "failed": 1}, "ts": 1010},
]
GATE_SNAP = {"status": "awaiting_approval", "proposal": PROPOSAL, "planned_call": PLANNED,
             "awaiting_decision": True, "progress_log": PROGRESS, "report": None}

RESOLVED_REPORT = {
    "root_cause_hypothesis": PROPOSAL["root_cause"],
    "action_taken": {"tool": "resync_connection", "action": "resync_connection"},
    "verification_result": "passed",
    "message": None,
    "after_metrics": [{"check_name": "freshness", "table": "account_holders", "column": None,
                       "before_value": 4541, "after_value": 0, "before_passed": False, "after_passed": True}],
    "verification": {"before_after": [{"check_name": "freshness", "table": "account_holders", "column": None,
                     "before_value": 4541, "after_value": 0, "before_passed": False, "after_passed": True}]},
    "time_to_resolution": {"total": "3m11s", "agent": "2m34s", "sync_wait": "37s", "human_wait": "0s"},
}
RESOLVED_SNAP = {"status": "resolved", "proposal": None, "report": RESOLVED_REPORT,
                 "time_to_resolution": RESOLVED_REPORT["time_to_resolution"],
                 "progress_log": PROGRESS + [{"stage": "acting", "detail": {"action": "resync_connection"}, "ts": 1012},
                                             {"stage": "verifying", "detail": {"poll": 3, "elapsed_seconds": 37}, "ts": 1049}]}


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 920})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_function(
            "document.querySelector('#conn') && document.querySelector('#conn').options.length > 0",
            timeout=30000)
        page.screenshot(path=str(OUT / "landing.png"))
        print("captured landing.png")

        # paint the gate from real data (no write)
        page.evaluate("(s) => { document.getElementById('runCard').classList.remove('hidden'); render(s); }", GATE_SNAP)
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "gate.png"))
        print("captured gate.png")

        # paint the resolved report from real data
        page.evaluate("(s) => { document.getElementById('runCard').classList.remove('hidden'); render(s); }", RESOLVED_SNAP)
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "resolved.png"), full_page=True)
        print("captured resolved.png")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
