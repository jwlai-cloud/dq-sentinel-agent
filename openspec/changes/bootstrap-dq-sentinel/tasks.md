## 1. Repo + Cloud Bootstrap (Week 1, days 1-2)

- [ ] 1.1 Create `LICENSE` (Apache-2.0 verbatim) at repo root
- [ ] 1.2 Create `README.md` stub with project name, one-liner, hosted URL placeholder, repo URL placeholder, license badge, hackathon track callout
- [ ] 1.3 `git init`, first commit, push to GitHub `dq-sentinel-agent` (public), set License field in repo About so it renders in sidebar
- [ ] 1.4 Create GCP project `dq-sentinel-hackathon`; enable Vertex AI, BigQuery, Secret Manager, Cloud Run APIs
- [ ] 1.5 Provision BQ dataset `dq_sentinel`; create `baselines` table per spec `bigquery-dq-checks` §"Baseline storage contract"
- [ ] 1.6 Create Fivetran free-tier account; confirm whether on-demand `sync_connection` is allowed on free tier (resolves Open Question 1 in design.md)
- [ ] 1.7 Stand up Sheets → Fivetran → BQ for `customers`, `orders`, `products` sheets (PRD §8)
- [ ] 1.8 Store Fivetran API key in Secret Manager as `FIVETRAN_API_KEY`

## 2. Agent Builder + Fivetran MCP Spike (Week 1, days 3-5)

- [ ] 2.1 Clone `github.com/GoogleCloudPlatform/agent-starter-pack`; run the hello-world Agent Builder agent end-to-end against a custom Python tool
- [ ] 2.2 Stand up Fivetran MCP server (`fivetran/fivetran-mcp`) standalone; confirm `list_connections` returns the live Sheets connections
- [ ] 2.3 Spike: register Fivetran MCP into Agent Builder. Decide between direct MCP support vs Python-subprocess wrapper (resolves Open Question 2 in design.md)
- [ ] 2.4 Pin `GEMINI_MODEL_ID = "gemini-2.5-pro"` in a single config module; verify availability in chosen region
- [ ] 2.5 Demo break scenario #1 (schema rename) on the Sheets source; confirm it lands in BQ with the expected nulls

## 3. Capability: `fivetran-integration` (Week 2, days 1-3)

- [ ] 3.1 Register all four read tools (`list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`) into Agent Builder for pre-approval steps
- [ ] 3.2 Implement application-side wrappers for the four write tools, NOT registered with the model
- [ ] 3.3 Implement the action→write-tool routing per spec `fivetran-integration` §"Remediation execution mapping"
- [ ] 3.4 Test: model in step 4 cannot enumerate or call any write tool

## 4. Capability: `bigquery-dq-checks` (Week 2, days 4-5)

- [ ] 4.1 Implement `dq_check_row_count(connection_id, table)` parameterized BQ tool returning structured result per spec
- [ ] 4.2 Implement `dq_check_null_rate(connection_id, table, column)` parameterized BQ tool
- [ ] 4.3 Implement `dq_check_freshness(connection_id, table, sla_minutes)` parameterized BQ tool
- [ ] 4.4 Implement `seed_baselines(connection_id)` operation writing rows into `dq_sentinel.baselines`
- [ ] 4.5 Implement table-allowlist validation (rejects unknown table names; rejects SQL-in-table-name attacks per spec scenario)
- [ ] 4.6 Set BQ custom quota on the GCP project to cap demo cost

## 5. Capability: `agent-loop` (Week 3, days 1-2)

- [ ] 5.1 Wire the 7-step orchestration in Agent Builder using only the registered read tools + the BQ DQ tools + `propose_remediation`
- [ ] 5.2 Implement the "baseline missing" precondition that terminates the loop with a clear error
- [ ] 5.3 Implement manual trigger endpoint ("Run scan now") callable from frontend
- [ ] 5.4 Implement incident report struct + emission on every completed run (resolved / unresolved / no-issue)

## 6. Capability: `diagnosis-and-remediation` (Week 3, days 3-4)

- [ ] 6.1 Define `propose_remediation` tool schema per spec; register only in step 4
- [ ] 6.2 Implement payload validation with up-to-2 retries on invalid payloads
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
