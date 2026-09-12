# Investigation service

The Investigation service implements the evidence-first multi-agent block in the
project architecture. It accepts the shared `InvestigationRequest`, retrieves
read-only facts through Agent Gateway, dynamically selects specialist agents, applies
deterministic scoring and stop rules, and returns the shared `InvestigationResult`.

## Runtime flow

1. Validate the shared request and resolve its immutable scoreboard reference.
2. Preserve Detection evidence in an evidence ledger.
3. Discover the current MCP tool schemas from Agent Gateway.
4. Build a case-type queue from subject affinity, evidence/trigger relevance, and the
   configured System agent priority; the highest routing score runs first.
5. Give each selected specialist only its role-scoped tool allowlist and remaining
   budget. The specialist may answer immediately or request one bounded lookup at a
   time through the OpenAI Responses function-calling loop.
6. Preserve every specialist's raw item scores, reject uncited or unknown score items,
   and calculate an evidence-weighted specialist aggregate in application code.
7. Combine valid specialist aggregates, validate findings, and evaluate deterministic
   stopping conditions after each agent.
8. Return findings, evidence, ordered agent invocations, raw and aggregated specialist
   results, the System scoreboard state, verdict, confidence, and stop reason.

Stop reasons match the shared contract: direct evidence, fraud threshold, legitimate
counterevidence, exhausted budget, diminishing returns, or insufficient evidence.
Tool and agent failures degrade independently without allowing unsupported scores.

Environment integration uses the simulation-aware views exposed by the dummy database.
The orchestrator does not prefetch domain data; each specialist decides whether a
lookup is necessary. Agent Gateway remains the only execution path.

| Tool group | Order | Chat | Marketplace info |
| --- | --- | --- | --- |
| Canonical records/replay | `get_evidence_records`, `get_environment_overview` | same | same |
| Account and graph | account activity/security, shared IP/device, entity neighbors, previous cases | same | account activity, shared IP/device, entity neighbors, previous cases |
| Commerce | commerce links, shared payment instruments | — | commerce links, shared payment instruments |
| Conversation/indicator | — | conversation accounts, exact indicator accounts/prevalence, existing VirusTotal URL/domain reports | — |
| Marketplace/association | — | — | association seeds, reused product images |

`database_health` is reserved for readiness checks. `search_accounts` is intentionally
not exposed to specialists because an investigation starts from known subjects and
should not perform an unbounded population scan.

Static records are also bounded by `simulation_state.simulation_time`, so an
investigation cannot observe a future event from the seeded scenario.

Each specialist returns a whole-number 0–5 fraud-risk score plus confidence and
evidence IDs for every category it actually investigated. Specialists receive the
allowed category names but never their deterministic weights. Application code
normalizes each raw score to 0–1, multiplies the private category weight by confidence,
and calculates the weighted mean of validated items. Coverage and all weighted
contributions are returned beside the untouched raw analysis. The orchestrator
combines specialist scores using confidence × coverage.

`config/scoreboard.development.json` mirrors the System-owned scoreboard schema,
including nested budget, stopping rules, agent policies, usage, and per-agent usage.
The local cost is reported as `0.0` because no pricing policy is available; token,
tool, agent, and investigation-step budgets are enforced.

## Package boundaries

- `api`: HTTP routes and transport concerns.
- `domain`: shared-contract mirrors and internal structured models.
- `core`: orchestration, dynamic routing, budgets, and stop decisions.
- `agents`: specialist definitions and common interface.
- `gateways`: MCP and OpenAI adapters.
- `evidence`: collection, deduplication, and citation validation.
- `scoring`: deterministic score calculation.
- `policies`: immutable scoreboard configuration resolution.
- `prompts`: version-controlled, injection-resistant specialist instructions.
- `config`: local development configuration only.
- `tests`: unit and API tests using fake external clients (no API usage).

## API

- `GET /health`: process liveness.
- `GET /ready`: Agent Gateway and PostgreSQL readiness via `database_health`.
- `POST /investigate`: execute an investigation.
- `/docs` and `/openapi.json`: generated FastAPI/OpenAPI documentation.

Containers should use `INVESTIGATION_URL=http://investigation:8000`; host code should
use `INVESTIGATION_URL=http://localhost:10002`.

Example request:

```bash
curl -X POST http://localhost:10002/investigate \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: demo-investigation-1' \
  -d '{
    "case_id": "case-demo-1",
    "detection_result": {
      "detection_id": "detection-demo-1",
      "subject": {"type": "account", "id": "ACC-0001"},
      "detected": true,
      "triggers": [{
        "type": "manual_review",
        "detector": "rule_based",
        "reason": "Review recent account activity",
        "evidence_refs": ["LOG-0001"]
      }],
      "evidence": [{
        "id": "LOG-0001",
        "source": "detection",
        "type": "login_event",
        "data": {"device_id": "DEV-0001"}
      }]
    },
    "scoreboard_config_ref": {"version": "development-v1"}
  }'
```

## Development

```bash
python -m pytest -q
docker compose up -d --build investigation
```

`OPENAI_API_KEY` is read only from the untracked root `.env`. The Responses request
uses `store=false`, disables parallel tool calls, and preserves the full response
output plus each `function_call_output` between stateless turns. Tests never send
network requests or consume model quota.
