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
