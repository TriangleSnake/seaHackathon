# Environment Dummy Database

This directory defines a deterministic PostgreSQL 16 dummy database for a
fictional Taiwanese marketplace. It contains normal marketplace activity,
legitimate edge cases, and a small number of suspicious multi-event sequences.
It does not contain a fraud classifier or ground-truth columns.

## Start

From the repository root:

```bash
cp .env.example .env
docker compose up -d
docker compose ps
docker compose logs postgres
```

Initialization runs `schema.sql` and then `seed.sql` only when the named volume
is empty. The PostgreSQL container is named `environment-db`; its Compose
service name remains `postgres` so existing repository services continue to
resolve it.

## Connect

From another container on `fraud-intelligence-network`:

```text
postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
```

From the host:

```text
postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}
```

With the values from `.env.example`, the database name is
`fraud_intelligence`. These are local development credentials only; replace
them outside an isolated development machine.

## Run integrity tests

```bash
docker compose exec -T postgres \
  psql -U "${POSTGRES_USER:-fraud}" \
  -d "${POSTGRES_DB:-fraud_intelligence}" \
  -v ON_ERROR_STOP=1 \
  -f /workspace/environment/tests/integrity.sql
```

The test exits nonzero for missing tables or views, invalid temporal ordering,
orphaned business relationships, future rows leaking through replay views,
forbidden answer columns, and insufficient seed counts.

## Simulation time

The seed stores the complete event timeline, but agents should query
`visible_*` views to avoid observing future events.

Show the current clock:

```bash
docker compose exec -T postgres \
  psql -U "${POSTGRES_USER:-fraud}" \
  -d "${POSTGRES_DB:-fraud_intelligence}" \
  -c "SELECT * FROM simulation_state;"
```

Move the clock forward:

```sql
SELECT advance_simulation_time(INTERVAL '1 day');
```

Set an exact time:

```sql
SELECT set_simulation_time(TIMESTAMPTZ '2026-09-05 12:00:00+08');
```

Reset to the initial seed time:

```sql
SELECT reset_simulation();
```

Replay-aware views include account status, logins, account security, messages,
product price and status, transaction status, payments, delivery, refunds,
disputes, and reports.

`visible_products` supplies the effective price/currency from the latest price
event at simulation time, falling back to the original product price before any
event. `products.price` intentionally remains the original price, not a mutable
current-price cache. Detection and product-detail/evidence queries in system-tools
use `visible_products`. Historical transaction amounts remain unchanged by repricing.

For an existing volume, install the non-destructive view migration **before**
starting the updated Detection/system-tools services:

```bash
docker compose exec -T postgres psql -U fraud -d fraud_intelligence -v ON_ERROR_STOP=1 \
  < environment/migrations/001-visible-products.sql
```

The migration only installs the view; it does not rewrite existing data. The
revised seed requires a fresh database. Do not re-run seed.sql into a populated
database. Existing local data was not replaced as part of this change.

## Quality and detector coverage

The revised seed has 120 accounts, 105 products, 107 transactions, 467 messages,
273 logins, 113 payment attempts and 12 disputes. Normal conversations alternate
buyer/seller turns and run during September 1–10 alongside suspicious sequences.
Payment retries precede delivery. Empty-package, listing-image and dispute chats
reference the same transactions/products as their related structured evidence.
Compatibility graph values match their cited login IP/device.

All seeded logins carry a consistently calculated `device_novel`: the first
successful observation of an account/device pair, ordered by timestamp then ID.
This assumes the synthetic login history is complete; real truncated histories
would require an unknown state instead of this assumption.

Fixtures exercise counts immediately below, at and above baseline thresholds for
message velocity (7/8/9), listing velocity (4/5/6), login devices (3/4/5), login
countries (2/3/4), and weekly disputes (1/2/3). Additional controls include repeated
logins from one device and payment retries using the same instrument. Switching
instruments and window expiration are also tested. Exceeding a threshold denotes
a signal, not a fraud label. Expected detector results are held in tests, never
in marketplace rows; these tests are not an accuracy benchmark.

Run `environment/tests/quality.sql` with psql after the existing integrity suite.
It validates event ordering, graph evidence, dialogue structure, novelty flags,
and price visibility immediately before/at a price change. Its clock changes are
rolled back. Detection's `tests/test_seed_coverage.py` exercises the boundary cases
against the actual service; configure `DETECTION_TEST_DATABASE_URL` to an isolated
database loaded from this seed.

## Rebuild the dummy database

```bash
docker compose down -v
docker compose up -d
```

`docker compose down -v` permanently deletes the local PostgreSQL volume. Use
it only when you intend to discard local changes and reload the deterministic
seed.

Restarting without `-v` preserves data:

```bash
docker compose restart postgres
```

## Dummy data design

The database begins with a normal marketplace baseline and legitimate cases
that can resemble fraud, such as travel logins, payment retries, an expected
flash-sale order spike, platform-hosted help links, and ordinary refunds.

Later simulation dates contain unlabeled suspicious sequences involving chat
phishing, account-access changes, payment-instrument churn, suspicious seller
listings, empty-package claims, and overlapping refund/dispute activity. No
marketplace row contains `is_fraud`, `fraud_type`, `fraud_role`,
`expected_detection`, or an injected-journey score.

## Cofacts attribution

The fictional suspicious messages were selected and adapted from ecommerce
scam themes in the Cofacts archive. Raw Cofacts archives, user identifiers,
phone numbers, account numbers, and original destinations are not loaded into
PostgreSQL. All generated links use reserved `.test` or `.invalid` domains.

> 本編輯資料取自「Cofacts 真的假的」訊息回報機器人與查證協作社群，採
> CC BY-SA 4.0 授權提供。若欲補充資訊請訪問 Cofacts LINE bot
> https://line.me/ti/p/@cofacts

Source: <https://huggingface.co/datasets/Cofacts/line-msg-fact-check-tw>
