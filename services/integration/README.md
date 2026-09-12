# Member 4 real CONFIG loop

`services.integration.real_loop` is the one-shot composition root for the first
real Member 4 demonstration. It uses the existing Evolution planner,
ConfigBuilder, Evaluator, Governance service, and VersionManager rather than
reimplementing their decisions.

The live run is intentionally constrained to:

- isolated PostgreSQL at `127.0.0.1:55432/fraud_intelligence`;
- scenario `taiwan-marketplace-20260912`;
- snapshot `2026-09-10T12:00:00+08:00`;
- Detection `rule_based` checks through real `POST /detect`;
- `rule_based.chat_request_phrases` CONFIG add/remove mutations.

The Environment adapter verifies database/user/scenario identity before it
calls the existing `set_simulation_time` function once. SnapshotGuard then
fails closed if the Environment identity changes during any evaluation.

Detection reads its baked baseline directory plus the host-published candidate
directory. The candidate directory is mounted read-only in Detection; only the
local ConfigBuilder writes it.

## Run

From the repository root, with the isolated validation database already
running:

```bash
python3 -m venv /tmp/member4-real-loop-venv
/tmp/member4-real-loop-venv/bin/pip install -r services/integration/requirements.txt
docker compose -f docker-compose.member4.yml up -d --build detection
/tmp/member4-real-loop-venv/bin/python -m services.integration.real_loop \
  preflight --env-file /path/to/repository/.env
/tmp/member4-real-loop-venv/bin/python -m services.integration.real_loop \
  run --env-file /path/to/repository/.env --human-approve
```

Preflight prints only key availability and the non-secret configured model. The
run emits JSON checkpoints and never prints the API key. Omit
`--human-approve` to stop at `needs_review`.

The activation checkpoint represents the existing VersionManager lifecycle.
Detection active-policy switching is not implemented; an activation adapter is
still required before a formal `DP-NNN` artifact can become Detection's default.

## Full demo-ready orchestration

`services.integration.demo_e2e` composes the shipped service boundaries in this
order:

```text
Environment verification
  -> Patrol -> Association -> Investigation
  -> Pattern Synthesis -> Evolution -> Capability Resolver
  -> CONFIG Builder -> Detection HTTP Evaluator
     or CODE -> isolated real Codex Builder validation
```

The discovery client marks the Patrol call as `association-first`; only that
request skips Patrol's legacy direct Investigation handoff. Existing Patrol calls
and job handoffs keep their previous behavior.

Start the normal discovery services plus the isolated Member 4 Detection runtime,
then run from the repository root:

```bash
COMPOSE_NETWORK_NAME=demo-ready-network docker compose \
  -f docker-compose.yml -f docker-compose.demo.yml up -d --build \
  postgres system-tools virustotal-tools agentgateway investigation patrol \
  association discovery-pipeline pattern-synthesis
MEMBER4_DETECTION_PORT=11002 docker compose \
  -f docker-compose.member4.yml -f docker-compose.member4.demo.yml \
  up -d --build detection
EVOLUTION_DETECTION_URL=http://127.0.0.1:11002 \
python -m services.integration.demo_e2e \
  --mode LIVE --env-file /path/to/repository/.env
```

For a reliable captured-data demonstration, pass two or more previously captured,
schema-valid real InvestigationResult files. The runner never relabels this mode
as live and never fabricates a PatternSpec:

```bash
python -m services.integration.demo_e2e \
  --mode REAL_FIXTURE --env-file /path/to/repository/.env \
  --fixture /path/to/real-investigation-1.json \
  --fixture /path/to/real-investigation-2.json
```

`NO_PATTERN` exits successfully after a clearly labelled stop. Concise stage JSON
is printed to stdout; the full audit artifact path is printed in the final line.
CODE candidates report `CODE BUILD / VALIDATION` only and do not claim a full
Evaluator closed loop.
