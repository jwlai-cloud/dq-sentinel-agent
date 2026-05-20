## ADDED Requirements

### Requirement: Diagnosis emits a `propose_remediation` tool call

The DIAGNOSE step (step 4) SHALL be implemented as a Gemini turn where the only available action is to invoke the internal `propose_remediation` tool. The tool's parameter schema SHALL be: `root_cause: string`, `severity: enum["CRITICAL","HIGH","MEDIUM","LOW"]`, `evidence: array of strings`, `action: enum["sync_connection","resync_connection","resync_tables","reload_schema","manual"]`, `targets: array of strings` (table names when action is `resync_tables`, else empty), `reasoning: string`, `manual_instructions: string` (required when action is `manual`, else empty string).

#### Scenario: Schema-drift diagnosis
- **WHEN** the inspect step reports a schema change and a null-rate spike on the renamed-away column
- **THEN** the model invokes `propose_remediation` with `action="resync_tables"`, `targets` containing the affected table, `severity="HIGH"`, `evidence` listing both the schema diff and the null spike, and a `root_cause` string referencing the column rename

#### Scenario: Manual-only diagnosis
- **WHEN** the inspect step reports a downstream issue that cannot be fixed via any Fivetran write tool (e.g. dbt model mismatch)
- **THEN** the model invokes `propose_remediation` with `action="manual"`, empty `targets`, and `manual_instructions` describing the user-facing change needed

### Requirement: Parameter validation rejects malformed proposals

Before reaching the approval gate, application code SHALL validate the `propose_remediation` payload against the schema. Invalid payloads (missing required fields, action/targets mismatch, unknown action) SHALL be returned to the model as a tool error, and the model SHALL retry up to 2 times before the loop terminates with `verification_result: "diagnosis_failed"`.

#### Scenario: Targets missing for resync_tables
- **WHEN** the model returns `action="resync_tables"` with `targets=[]`
- **THEN** the tool returns an error "resync_tables requires non-empty targets", the model retries, and on second failure the loop terminates without invoking the approval gate

### Requirement: Approval gate UX

The user-facing approval prompt SHALL display: the severity, the root-cause hypothesis, the evidence list, the proposed action and targets, and the underlying Fivetran MCP tool call that would execute on approval (with all arguments). The user SHALL be able to approve, reject (with optional reason), or modify the targets list before approving.

#### Scenario: Approve with modified targets
- **WHEN** the user removes one table from `targets` and clicks approve
- **THEN** step 6 invokes `resync_tables` with the user-edited targets, and the incident report records both the originally proposed targets and the executed targets

#### Scenario: Reject with reason
- **WHEN** the user clicks reject and enters "false positive — we knew about the schema change"
- **THEN** the rejection reason is added to the agent's context for the next iteration of step 4, and no Fivetran write tool is invoked

### Requirement: Post-execution verification

After step 6 successfully invokes a Fivetran write tool, step 7 SHALL: (1) poll `get_connection_state` at 30-second intervals up to 30 minutes until the triggered sync reports completion, (2) re-run every DQ check that failed in step 3, (3) compare results to baseline, (4) record before/after metrics in the incident report. If polling times out, step 7 SHALL record `verification_result: "timed_out"`.

#### Scenario: Successful verification
- **WHEN** step 7 polls and detects sync completion within 30 minutes, then re-runs the originally failing null-rate check and it now passes
- **THEN** the incident report records `verification_result: "passed"`, the time-to-resolution from initial detection to verification, and the before/after null-rate values

#### Scenario: Polling timeout
- **WHEN** step 7 polls for 30 minutes without sync completing
- **THEN** the incident report records `verification_result: "timed_out"` and surfaces a "sync still in progress" message in the frontend

### Requirement: Time-to-resolution metric

The incident report SHALL compute time-to-resolution as the wall-clock interval between step 1 start and step 7 completion, and SHALL separately record the portion of that time spent waiting on Fivetran sync (so the agent-attributable time is distinguishable from sync-latency-attributable time).

#### Scenario: TTR breakdown
- **WHEN** a run completes with total TTR of 8 minutes, of which 7 were spent in step 7 polling
- **THEN** the incident report records `time_to_resolution_total: "8m"` and `time_to_resolution_agent: "1m"`
