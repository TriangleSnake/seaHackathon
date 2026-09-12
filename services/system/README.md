# System Control Plane

System owns trigger policies, persistent schedules and cross-agent job lifecycle. The
Dashboard configures and observes this service; it does not run timers in the browser.

## Phase 1 routes

- Replay cursor events → `POST /detect`
- Persistent Patrol schedule → `POST /patrol/jobs` → remote job reconciliation
- Manual Detection and Patrol jobs through `POST /jobs`

Investigation and Association remain valid job targets in the shared contract, but their
automatic handoffs are intentionally not connected in phase 1.

All seeded trigger policies and schedules are disabled by default. Enable them through
`PUT /control/triggers/{policy_id}` or `PUT /control/schedules/{schedule_id}`.

Dashboard model controls are exposed through `GET /control/models` and
`PUT /control/models/{component}`. The selected model and reasoning effort are
snapshotted into each new System job and forwarded as request-scoped headers, so
running jobs are never changed and concurrent agents cannot overwrite one another.
Environment model variables remain startup fallbacks for direct service calls.
