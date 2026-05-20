## ADDED Requirements

### Requirement: Seven-step orchestration

The agent SHALL execute the following steps in order on every run, with each step's output being the next step's input: (1) SCAN, (2) DETECT, (3) INSPECT, (4) DIAGNOSE, (5) RECOMMEND+APPROVE, (6) ACT, (7) VERIFY. Steps 1-4 and 7 SHALL run without human input. Step 5 SHALL block until an approval decision is received. Step 6 SHALL execute only if step 5 returns "approved".

#### Scenario: All approved end-to-end
- **WHEN** the agent is triggered against a Fivetran connection with a known sync failure and a seeded baseline
- **THEN** the agent runs steps 1-4 autonomously, presents a remediation proposal in step 5, and on user approval executes step 6 followed by step 7 within a single run

#### Scenario: User rejects remediation
- **WHEN** the agent reaches step 5 and the user rejects the proposed remediation with a reason
- **THEN** the agent does NOT invoke any Fivetran write tool, returns to step 4 with the rejection reason in context, and produces a revised diagnosis or terminates with an "unresolved" incident report

#### Scenario: Triggered without baseline
- **WHEN** the agent is triggered against a connection that has no baseline rows in `dq_sentinel.baselines`
- **THEN** the agent terminates with a "baseline missing — run seed first" error and does not invoke any inspect, diagnose, or act step

### Requirement: Approval gate is structurally unbypassable

The Gemini model invoked in steps 1-5 SHALL NOT have any Fivetran write tool registered in its tool set. Fivetran write tools SHALL be invocable only by application code in step 6, only after step 5 returns "approved" with a validated remediation payload.

#### Scenario: Model attempts direct write
- **WHEN** the diagnosis-step model output names a Fivetran write tool by name (e.g. `sync_connection`) and tries to call it directly
- **THEN** the tool call fails because the tool is not registered, and the model is constrained to use the `propose_remediation` internal tool instead

### Requirement: Triggering

The agent SHALL be triggerable manually via the frontend ("Run scan now") for P0. Scheduled and webhook triggers are out of scope for P0.

#### Scenario: Manual trigger
- **WHEN** a user clicks "Run scan now" in the frontend
- **THEN** the agent loop begins at step 1 within 5 seconds of the click

### Requirement: Incident report emission

On every completed run (whether resolved, unresolved, or no-issue), the agent SHALL emit a structured incident report containing: triggered_at, detected_issues, root_cause_hypothesis, remediation_proposed, approval_decision, action_taken, verification_result, before_metrics, after_metrics, time_to_resolution.

#### Scenario: Resolved incident
- **WHEN** a run completes with step 7 reporting all DQ checks passing post-remediation
- **THEN** the incident report records `verification_result: "passed"` and includes both before and after metric values

#### Scenario: No-issue scan
- **WHEN** a run completes with step 2 detecting no issues
- **THEN** the incident report records `detected_issues: []` and skips steps 3-7

### Requirement: Baseline seeding step

The system SHALL expose a separate `seed_baselines(connection_id)` operation that captures current row counts, per-column null rates, and schema snapshot into `dq_sentinel.baselines` for a named connection. This operation is invoked once per connection before the agent loop runs against that connection for the first time.

#### Scenario: Seed against clean source
- **WHEN** `seed_baselines("conn_sheets_customers")` is invoked while the source data is known-good
- **THEN** `dq_sentinel.baselines` contains one row per metric (row_count, null_rate per column, schema fingerprint) for that connection with `metric_version = 1`
