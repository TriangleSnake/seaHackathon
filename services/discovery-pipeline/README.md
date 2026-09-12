# Upstream Discovery Pipeline

This isolated service implements the real upstream flow without changing the
published Patrol, Association, or Investigation APIs:

```text
POST /pipeline/run
  -> POST PATROL_URL/patrol/run
  -> for each validated discovery, sequentially:
       POST ASSOCIATION_URL/associate
       POST INVESTIGATION_URL/investigate
```

The request to `/pipeline/run` is the existing `PatrolRequest`. The response is
an internal `UpstreamPipelineResult` containing the Patrol result and one audit
record per discovery, including deterministic case identity, stage timestamps,
requests, results, and explicit errors.

## Failure policy

- A Patrol transport or contract failure fails the complete pipeline.
- An Association failure fails that discovery closed and skips its Investigation.
- A valid empty Association result still proceeds to Investigation with Patrol evidence.
- An Investigation failure is recorded for that discovery.
- Other discoveries continue, producing `partial_failure` when appropriate.

All processing is sequential to retain deterministic audit order. Transport
failure is never interpreted as a normal/no-fraud result. The endpoint returns
the auditable pipeline document even when its internal status is `failed`; HTTP
errors remain reserved for an invalid pipeline request or an unhandled service bug.

## Configuration

- `PATROL_URL` (default `http://patrol:10003`)
- `ASSOCIATION_URL` (default `http://association:10004`)
- `INVESTIGATION_URL` (default `http://investigation:8000`)
- `DISCOVERY_PIPELINE_TIMEOUT_SECONDS` (default `30`)
- `SCOREBOARD_CONFIG_VERSION` (default `development-v1`)
- `DISCOVERY_PIPELINE_SCHEMA_DIR` (defaults to repository `shared/schemas`)

Build from the repository root because the image includes shared schemas:

```bash
docker build -f services/discovery-pipeline/Dockerfile -t discovery-pipeline .
```

For local development:

```bash
cd services/discovery-pipeline
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/uvicorn app.main:app --port 10006
```

## Pattern Synthesis handoff

Pattern Synthesis is intentionally not implemented. Full System Integration can
call `app.adapters.collect_investigation_results(pipeline_result)` to obtain only
successful `InvestigationResult` documents together with Patrol and Association
provenance. Graph nodes and edges remain in the Association result; only valid
Association `Evidence` enters Investigation's `existing_evidence` field.

## Full System Integration

No Compose or System control-plane route is changed by this branch. Integration
should add this service with repository-root Docker build context, route new
upstream runs to `POST /pipeline/run`, and pass the collector output to Pattern
Synthesis. Keep the full `UpstreamPipelineResult` as the audit record.

The pipeline marks its Patrol request with
`X-Upstream-Orchestration: association-first`. Patrol treats that internal marker
as a request-scoped gate for its legacy direct Investigation handoff, so this path
performs Association and then Investigation exactly once. Calls without the marker,
including existing job handoffs, retain the legacy behavior.
