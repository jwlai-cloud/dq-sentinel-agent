## 1. Repo + Cloud Bootstrap (Week 1, days 1-2)

- [x] 1.1 Create `LICENSE` (Apache-2.0 verbatim) at repo root
- [x] 1.2 Create `README.md` stub with project name, one-liner, hosted URL placeholder, repo URL placeholder, license badge, hackathon track callout
- [x] 1.3 `git init`, first commit, push to GitHub `dq-sentinel-agent` (public), set License field in repo About so it renders in sidebar — https://github.com/jwlai-cloud/dq-sentinel-agent
- [x] 1.4 Use existing GCP project `agent-era` (region `us-central1`); enable `aiplatform`, `bigquery`, `secretmanager`, `run`, `cloudbuild`, `iam` APIs
- [x] 1.5 Provision BQ dataset `agent-era.dq_sentinel` in `us-central1`; create `baselines` table (PARTITION BY DATE(captured_at), CLUSTER BY connection_id, table_name, metric) per spec `bigquery-dq-checks` §"Baseline storage contract"
- [ ] 1.6 Create Fivetran free-tier account; confirm whether on-demand `sync_connection` is allowed on free tier (resolves Open Question 1 in design.md)
- [ ] 1.7 Stand up Sheets → Fivetran → BQ for `customers`, `orders`, `products` sheets (PRD §8)
- [ ] 1.8 Store Fivetran API key in Secret Manager as `FIVETRAN_API_KEY` in project `agent-era`

## 2. Agent Builder + Fivetran MCP Spike (Week 1, days 3-5)

- [x] 2.1 ADK hello-world end-to-end — DONE 2026-06-02. Lean hand-rolled ADK project (`dq_sentinel/{config,agent}.py`, not the starter-pack) instead of agent-starter-pack (fewer files, full control). Gemini 3.5 Flash → ADK `McpToolset` (read-only `tool_filter`) → Fivetran MCP → live `list_connections` → coherent health report. Auth via runtime SA `dq-sentinel-runtime@agent-era` (key in `.secrets/`, gitignored; same SA for Cloud Run later). KEY GOTCHA: Gemini 3.x served from Vertex location `global`, not `us-central1` (regional → 403). Wiring smoke (`scripts/smoke_agent.py`) proves tool_filter exposes exactly the 5 read tools, zero write tools leaked.
- [x] 2.2 Stand up Fivetran MCP server (`fivetran/fivetran-mcp`) standalone; confirm `list_connections` returns the live connections — DONE 2026-06-02. `uvx --from git+https://github.com/fivetran/fivetran-mcp fivetran-mcp`, server v1.27.2, 77 tools (all 9 PRD Appendix A tools present), auth via `FIVETRAN_API_KEY`+`FIVETRAN_API_SECRET` (two separate env vars — NOT the combined base64 blob). Returns full status payload (setup_state, sync_state, schema_status, warnings[], schedule). Quirk: every tool requires a `schema_file` arg = a fixed path string the caller must pass to confirm it read the OpenAPI def (e.g. `open-api-definitions/connections/list_connections.json`).
- [ ] 2.3 Spike: register Fivetran MCP into Agent Builder. Decide between direct MCP support vs Python-subprocess wrapper (resolves Open Question 2 in design.md). NOTE: MCP exposes all 77 tools at once; the structural approval gate (design D4) needs us to surface only read tools to Gemini in steps 1-5. Lever found: `FIVETRAN_ALLOW_WRITES=false` env var disables all write tools at the server level — run a read-only MCP instance for steps 1-5, a write-enabled path only for step 6.
- [x] 2.4 Pin `GEMINI_MODEL_ID = "gemini-3.5-flash"` in a single config module (`dq_sentinel/config.py`) — DONE. Verified available + callable on Vertex at location `global` (not us-central1).
- [x] 2.5 Demo break scenario #1 (schema rename) — DONE 2026-06-02. Renamed `base_apr`→`headline_apr` in the loan_products sheet, synced. Result in BQ: both columns present, `base_apr` 100/100 NULL, `headline_apr` 0/100 NULL, values migrated exactly — textbook PRD scenario 1. FINDING: Fivetran `get_connection_schema_config` for a Sheets connector returns a thin payload (no column-level drift detail); the reliable schema-drift signal is **BQ `INFORMATION_SCHEMA.COLUMNS`** (per the `bigquery-dq-checks` schema-mismatch check). loan_products table currently left in the broken state as a test fixture for building the detectors. (loan_products Fivetran connection id = `subjected_synthesis`.)

## 3. Capability: `fivetran-integration` (Week 2, days 1-3)

- [ ] 3.1 Register all four read tools (`list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`) into Agent Builder for pre-approval steps
- [ ] 3.2 Implement application-side wrappers for the four write tools, NOT registered with the model
- [ ] 3.3 Implement the action→write-tool routing per spec `fivetran-integration` §"Remediation execution mapping"
- [ ] 3.4 Test: model in step 4 cannot enumerate or call any write tool

## 4. Capability: `bigquery-dq-checks` (Week 2, days 4-5)

- [x] 4.1 `dq_check_row_count` (dq_sentinel/bq.py) — vs baseline, >30% deviation fails. Verified.
- [x] 4.2 `dq_check_null_rate` — vs baseline, >2x fails (any-null fails when baseline=0). Verified: base_apr 0→100% caught.
- [x] 4.3 `dq_check_freshness` — minutes since MAX(_fivetran_synced) vs SLA. Verified.
- [x] 4.4 `seed_baselines(table, connection_id)` — writes row_count + per-column null_rate + schema_fingerprint via load job (read-after-write reliable). Seeded account_holders + transactions. Also added `dq_check_schema_mismatch` (INFORMATION_SCHEMA vs baseline fingerprint) — the reliable schema-drift detector per 2.5 finding.
- [x] 4.5 Table-allowlist (`KNOWN_TABLES`) + column validation against INFORMATION_SCHEMA; unknown table/column raises. No free-form SQL reaches BQ.
- [ ] 4.6 Set BQ custom quota on the GCP project to cap demo cost (low priority — tiny dataset, credits ample)

## 5. Capability: `agent-loop` (Week 3, days 1-2)

- [ ] 5.1 Wire the 7-step orchestration in Agent Builder using only the registered read tools + the BQ DQ tools + `propose_remediation`
- [ ] 5.2 Implement the "baseline missing" precondition that terminates the loop with a clear error
- [ ] 5.3 Implement manual trigger endpoint ("Run scan now") callable from frontend
- [ ] 5.4 Implement incident report struct + emission on every completed run (resolved / unresolved / no-issue)

## 6. Capability: `diagnosis-and-remediation` (Week 3, days 3-4)

- [x] 6.1 `propose_remediation` tool (dq_sentinel/diagnose.py) — typed params (Literal enums for severity/action) ARE the diagnosis schema (design D3). Internal tool, no Fivetran side effect. Verified: Gemini 3.5 Flash diagnosed the live loan_products drift → action=resync_tables, targets=[loan_products], severity=HIGH, evidence citing real numbers.
- [◐] 6.2 `validate_payload()` implemented (action/targets/manual/severity rules). Verified PASS on the live proposal. Still TODO: the up-to-2-retry loop (wires into the agent-loop step 4 control flow, section 5).
- [ ] 6.3 Implement approval-gate UI: severity badge, root cause, evidence list, exact MCP call preview, approve/reject/modify-targets controls
- [ ] 6.4 Implement step 7 verification: poll `get_connection_state` at 30s intervals, 30-min timeout, re-run originally-failing checks, record before/after metrics
- [ ] 6.5 Implement TTR breakdown (total vs agent-attributable) per spec scenario

## 7. End-to-End Demo Scenario (Week 3, day 5)

- [ ] 7.1 Wire the schema-drift + null-spike scenario (PRD §8 scenario 1) end-to-end: seed → break sheet → trigger agent → approve → verify
- [ ] 7.2 Wire the freshness-violation scenario (pause connector)
- [ ] 7.3 Wire the data-loss scenario (delete 50% of orders rows)
- [ ] 7.4 Confirm each scenario completes within the on-demand sync budget verified in task 1.6

## 8. Hosting + Submission (Week 4)

- [ ] 8.1 Containerize agent + frontend; deploy to Cloud Run; confirm public hosted URL
- [ ] 8.2 Smoke test the hosted URL with one demo scenario
- [ ] 8.3 Update `README.md`: actual hosted URL, screenshots, quickstart, license badge correct
- [ ] 8.4 Record 3-minute demo video (English, narrated). Pre-stage break before recording per design.md D7
- [ ] 8.5 Upload video to YouTube/Vimeo with English subtitles
- [ ] 8.6 Submit Devpost form: hosted URL, repo URL, video URL, track = Fivetran, text description covering features/tech/data sources/learnings
- [ ] 8.7 Verify GitHub repo License field is detected and visible in sidebar

## 9. Buffer / Stretch (Week 4 if P0 done)

- [ ] 9.1 Add duplicate-detection DQ check (P1)
- [ ] 9.2 Add DQ dashboard view to frontend (P1)
- [ ] 9.3 Add Markdown incident-report export (P1)
- [ ] 9.4 If Gemini 3 has shipped, swap `GEMINI_MODEL_ID` and re-run all 6 break scenarios
