# Investigation service

This directory owns the fraud investigation multi-agent service.

The service will accept the shared `InvestigationRequest`, gather evidence through
the MCP agent gateway, coordinate specialized agents, and return the shared
`InvestigationResult`. Business behavior is intentionally added one reviewed
feature at a time.

## Package boundaries

- `api`: HTTP routes and transport concerns.
- `domain`: request, response, and internal domain models.
- `core`: multi-agent orchestration.
- `agents`: specialized investigation agents and their shared contract.
- `gateways`: MCP and OpenAI adapters.
- `evidence`: evidence collection, validation, and deduplication.
- `scoring`: deterministic score calculation.
- `policies`: immutable scoreboard configuration resolution.
- `prompts`: version-controlled system prompts.
- `config`: local development configuration only.
- `tests`: unit and contract tests using fake external clients.

The externally published port is `10002` by default; the container listens on
`8000`.

## Current API

- `GET /health` reports process liveness.
- `GET /ready` checks Agent Gateway and PostgreSQL through `database_health`.
- `POST /investigate` validates the shared request contract and returns a schema-
  compatible placeholder until the orchestrator is implemented. Placeholder
  responses have `X-Investigation-Placeholder: true`, `verdict: unknown`, and do
  not represent an actual fraud decision.

Other containers in this Compose project should use:

```text
INVESTIGATION_URL=http://investigation:8000
```

Code running directly on the host should use:

```text
INVESTIGATION_URL=http://localhost:10002
```

The investigation operation is therefore `POST ${INVESTIGATION_URL}/investigate`.

Run the service with the rest of the local stack:

```bash
docker compose up -d --build investigation
```
