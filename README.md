# Fraud Intelligence System — Shared Schemas v0.2

Use JSON Schema Draft 2020-12.

Recommended REST contracts:

- POST /detect
  - request: detection.schema.json#/$defs/DetectionRequest
  - response: detection.schema.json#/$defs/DetectionResult
- POST /investigate
  - request: investigation.schema.json#/$defs/InvestigationRequest
  - response: investigation.schema.json#/$defs/InvestigationResult
  - Docker Compose URL: `http://investigation:8000/investigate`
  - host URL: `http://localhost:10002/investigate`
  - runs the evidence-first orchestrator and three specialist agents
- POST /patrol/run
  - request: patrol.schema.json#/$defs/PatrolRequest
  - response: patrol.schema.json#/$defs/PatrolResult
- POST /associate
  - request: association.schema.json#/$defs/AssociationRequest
  - response: association.schema.json#/$defs/AssociationResult
- POST /evolution/evaluate
  - request: evolution.schema.json#/$defs/EvolutionRequest
  - response: evolution.schema.json#/$defs/EvolutionResult
- POST /build
  - request: candidate.schema.json#/$defs/BuildRequest
  - response: candidate.schema.json#/$defs/CandidateResult
- POST /evaluate
  - request: evaluation.schema.json#/$defs/EvaluationRequest
  - response: evaluation.schema.json#/$defs/EvaluationResult
- POST /governance/review
  - request: governance.schema.json#/$defs/GovernanceRequest
  - response: governance.schema.json#/$defs/GovernanceResult

Dashboard mainly consumes the service schemas. Its own schema only defines mutation actions:
case review, appeal, and policy update.

Tracing recommendation:
use HTTP `X-Request-ID` and W3C `traceparent` headers instead of repeating trace metadata in every JSON body.

## Local agent tool gateway

The local stack uses the official Linux Foundation `agentgateway` as the MCP
proxy. Agents connect only to the gateway; it multiplexes the `system-tools` MCP
server for allow-listed PostgreSQL queries and the isolated `virustotal-tools` MCP
server for read-only external URL/domain reputation reports.
The host port binds to `127.0.0.1` so unauthenticated network clients cannot consume
the configured VirusTotal quota; containers continue to use `http://agentgateway:3000/mcp`.

```text
Agent -> http://localhost:3000/mcp -> agentgateway -> system-tools -> PostgreSQL
                                               `-> virustotal-tools -> VirusTotal API
```

Start the stack:

```bash
cp .env.example .env
docker compose up -d --build
```

Run the end-to-end smoke test:

```bash
./scripts/smoke-test-mcp.sh
```

The gateway exposes these read-only tools:

- `database_health`
- `search_accounts`
- `get_account_activity`
- `find_shared_ip_accounts`
- `find_shared_device_accounts`
- `get_entity_neighbors`
- `get_previous_cases`
- `get_evidence_records`
- `get_virustotal_reputation` (Chat Agent only)

No generic SQL execution tool is exposed. Add new database capabilities as
bounded domain tools so agents cannot bypass access controls or query limits.

The sample database is initialized only when the PostgreSQL volume is first
created. To apply schema changes to an existing development database, use a
migration or recreate the development volume intentionally.

Marketplace dummy data, simulation-time replay, connection details, and
integrity-test instructions are documented in
[`environment/README.md`](environment/README.md).


## v0.2 corrections

- Detection does **not** calculate the system fraud score.
  - It only emits `detected`, `triggers`, raw detector outputs, and evidence.
- Investigation does **not** define its own thresholds or budget.
  - It receives only an immutable `scoreboard_config_ref`.
- `scoreboard.schema.json` is owned by the System/control plane.
  - It defines scoring policy version, fraud/normal thresholds, agent/tool/step/token/cost budgets, stopping rules, and agent priorities.
- Investigation returns the resulting `ScoreboardState` for auditability/reproducibility.
