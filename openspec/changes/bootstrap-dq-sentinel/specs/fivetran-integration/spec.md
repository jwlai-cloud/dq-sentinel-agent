## ADDED Requirements

### Requirement: Fivetran MCP server is the sole Fivetran client

All Fivetran interactions SHALL go through the `fivetran/fivetran-mcp` MCP server. The system SHALL NOT call the Fivetran REST API directly. Authentication SHALL use a Fivetran API key stored in Google Secret Manager and injected into the MCP server's environment at startup.

#### Scenario: API key from Secret Manager
- **WHEN** the agent process starts
- **THEN** it reads `FIVETRAN_API_KEY` from Secret Manager (not from a plaintext env file) and passes it to the Fivetran MCP server subprocess

### Requirement: Read tools available pre-approval

The following Fivetran MCP read tools SHALL be registered with the Gemini model in steps 1-5 of the agent loop: `list_connections`, `get_connection_details`, `get_connection_state`, `get_connection_schema_config`.

#### Scenario: Scan step uses list_connections
- **WHEN** the agent enters step 1
- **THEN** the model invokes `list_connections` and receives a list of connection IDs and statuses

### Requirement: Write tools unavailable pre-approval

The following Fivetran MCP write tools SHALL NOT be registered with the Gemini model in any pre-approval step: `sync_connection`, `resync_connection`, `resync_tables`, `reload_connection_schema_config`. They SHALL be invoked only by application code in step 6 of the agent loop.

#### Scenario: Diagnosis step has no write tools
- **WHEN** the agent enters step 4 (diagnose) and the model lists available tools
- **THEN** none of the four write tools appear in the model's tool set

### Requirement: Remediation execution mapping

When step 5 returns "approved" with a validated `propose_remediation` payload, step 6 SHALL invoke exactly one Fivetran MCP write tool determined by the payload's `action` field: `sync_connection` for action=`sync_connection`, `resync_connection` for action=`resync_connection`, `resync_tables` (passing payload.targets as the tables argument) for action=`resync_tables`, `reload_connection_schema_config` for action=`reload_schema`. For action=`manual`, step 6 SHALL skip Fivetran invocation and record the manual instructions in the incident report.

#### Scenario: Targeted resync
- **WHEN** approval is granted on a payload with `action=resync_tables` and `targets=["customer_orders"]`
- **THEN** step 6 invokes `resync_tables(connection_id, ["customer_orders"])` and records the MCP call ID in the incident report

#### Scenario: Manual remediation
- **WHEN** approval is granted on a payload with `action=manual` and a description
- **THEN** step 6 makes no MCP write call, records the description as "manual action recommended", and step 7 still re-runs DQ checks to confirm whether the issue resolved itself
