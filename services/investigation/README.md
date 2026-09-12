# Investigation service

The Investigation service implements the evidence-first multi-agent block in the
project architecture. It accepts the shared `InvestigationRequest`, retrieves
read-only facts through Agent Gateway, uses an LLM Orchestrator to plan specialist
work and synthesize the final report, applies deterministic scoring and safety
limits, and returns the shared `InvestigationResult`.

## Runtime flow

1. Validate the shared request and resolve its immutable scoreboard reference.
2. Preserve Detection evidence in an evidence ledger.
3. Discover the current MCP tool schemas from Agent Gateway.
4. Ask the LLM Orchestrator to choose `order`, `chat`, or `marketplace_info` and
   provide a concrete investigation focus. It can later continue the same specialist
   with a new focus, select another specialist, or stop.
5. Give the selected specialist only its role-scoped tool allowlist and remaining
   budget. The specialist may answer immediately or request one bounded lookup at a
   time through the OpenAI Responses function-calling loop.
6. Preserve every specialist's raw item scores, reject uncited or unknown score items,
   and calculate an evidence-weighted specialist aggregate in application code.
7. Return only validated results, aggregate scores, coverage, open questions, and
   remaining budget to the Orchestrator. Private category weights are never exposed.
8. Repeat planning until the Orchestrator stops or Python enforces a hard budget.
9. Calculate the final verdict deterministically, then ask the Orchestrator to
   synthesize all Sub-agent results into the final Traditional Chinese report.
10. Return findings, evidence, ordered Orchestrator decisions, raw and aggregated
    specialist results, the report, System scoreboard, verdict, confidence, and stop
    reason.

Stop reasons match the shared contract: direct evidence, fraud threshold, legitimate
counterevidence, exhausted budget, diminishing returns, or insufficient evidence.
Tool and agent failures degrade independently without allowing unsupported scores.

Environment integration uses the simulation-aware views exposed by the dummy database.
The Orchestrator does not receive MCP tools and cannot prefetch domain data; each
specialist decides whether a lookup is necessary. Agent Gateway remains the only
tool execution path. A deterministic subject/relevance router is retained only as a
fallback if the LLM Orchestrator is unavailable.

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
contributions are returned beside the untouched raw analysis. Application code
combines specialist scores using confidence × coverage; the Orchestrator sees
aggregate values and coverage but not category weights.

`config/scoreboard.development.json` mirrors the System-owned scoreboard schema,
including nested budget, stopping rules, agent policies, usage, and per-agent usage.
The local cost is reported as `0.0` because no pricing policy is available. Token
usage is recorded but `max_tokens=0` disables the total-token stopping limit; tool,
Sub-agent-call, and investigation-step budgets remain enforced.

## Package boundaries

- `api`: HTTP routes and transport concerns.
- `domain`: shared-contract mirrors and internal structured models.
- `core`: the guarded planning loop, evidence flow, budgets, and stop enforcement.
- `agents`: the LLM Orchestrator and specialist definitions.
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
      "policy_ref": {"type": "detection", "version": "baseline-v1"},
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
