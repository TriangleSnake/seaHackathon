# Environment replay

Replay turns newly visible timestamped rows into Detection requests. Each batch
advances simulation time by 300 seconds and deduplicates affected subjects within
that batch. Data at the starting time is already visible and is not replayed;
events in `(start, end]` are included. This replays recorded event rows, not arbitrary
UPDATE statements on static columns. Record such changes as timestamped events.

Start dependencies, then replay one batch:

```sh
docker compose up -d --build detection
docker compose --profile replay run --rm --build replay python -u runner.py --once --step-seconds 300
```

Continuous replay (five simulated minutes every five real seconds):

```sh
docker compose --profile replay up -d --build replay
docker compose logs -f replay
docker compose stop replay
```

Stop replay before Evaluator baseline/candidate comparison and leave simulation
time unchanged. Restart with `docker compose --profile replay up -d replay`.
Failures terminate the runner; restarting resumes the pending batch with its
original policy, skipping persisted successes. Only one runner can hold the DB
advisory lock. During each Detection call the clock row is share-locked so clock
updates wait. External time changes between calls are detected and stop replay.
Do not run another replay or clock writer during evaluation.

Progress and full DetectionResult bodies live in `replay.batches` and `replay.jobs`
in PostgreSQL, separate from Environment tables. Inspect with:

```sql
SELECT * FROM replay.batches ORDER BY id DESC;
SELECT batch_id, kind, subject_id, result->>'detected' AS detected FROM replay.jobs;
```

Delivery is at least once: a crash after HTTP success but before committing the
result can repeat the request. Detection currently has no downstream side effects.
Results are saved here; automatically opening Investigation cases is not included.
Changing the simulation clock outside replay fails explicitly; use a fresh test DB
for a new timeline. Policies must already exist in the Detection container.

Mappings cover accounts, shops, products/images/prices/status, transactions/status,
payments, deliveries, refunds, disputes, messages/attachments, reviews, reports,
logins and account security/status. Messages also check the sender account;
products check the seller; disputes check the opener for aggregate rate detectors.
