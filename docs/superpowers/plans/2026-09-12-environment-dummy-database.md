# Environment Dummy Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a PostgreSQL dummy marketplace database with deterministic normal activity, hard negatives, suspicious event journeys, and simulation-time replay.

**Architecture:** Extend the repository's existing PostgreSQL schema without changing service code or breaking the columns queried by `system-tools`. Generate the normal baseline inside `seed.sql` using deterministic SQL and append explicit suspicious journeys whose rows remain unlabeled. Validate behavior through executable SQL assertions and clean-volume Docker checks.

**Tech Stack:** PostgreSQL 16 Alpine, Docker Compose, SQL initialization scripts, PostgreSQL constraints/indexes/views/functions

**Spec:** `docs/superpowers/specs/2026-09-12-environment-database-design.md`

## Global Constraints

- The current repository is authoritative when requirements conflict.
- Final project changes contain no Python generator, API, MCP server, or application service.
- Do not modify source files under `services/` or `agentgateway/`.
- Preserve the existing columns queried by `services/system-tools/app/server.py`.
- Use fixed IDs and timestamps; do not use `NOW()` in generated marketplace seed rows.
- Do not store real personal data, live malicious URLs, complete card numbers, CVV, bank accounts, fraud labels, expected detections, or injected-journey risk scores.
- Do not push or merge.

---

### Task 1: Establish failing database integrity tests

**Files:**
- Create: `environment/tests/integrity.sql`

**Interfaces:**
- Consumes: PostgreSQL schema initialized from `environment/schema.sql` and data initialized from `environment/seed.sql`.
- Produces: a `psql -v ON_ERROR_STOP=1` test that raises named exceptions for every violated invariant.

- [ ] **Step 1: Write the initial failing assertions**

Create `environment/tests/integrity.sql` with a transaction and `DO` blocks. Begin with required-table and count assertions so the current incomplete database fails for the intended reason:

```sql
\set ON_ERROR_STOP on
BEGIN;

DO $$
DECLARE
    missing_tables TEXT[];
BEGIN
    SELECT array_agg(required_name ORDER BY required_name)
      INTO missing_tables
      FROM unnest(ARRAY[
        'account_status_events', 'devices', 'account_security_events',
        'conversations', 'conversation_participants', 'message_attachments',
        'product_images', 'product_price_events', 'product_status_events',
        'reviews', 'transaction_status_events', 'payment_attempts',
        'delivery_events', 'refunds', 'disputes', 'simulation_state'
      ]) AS required_name
     WHERE to_regclass('public.' || required_name) IS NULL;

    IF missing_tables IS NOT NULL THEN
        RAISE EXCEPTION 'missing required tables: %', missing_tables;
    END IF;
END $$;

DO $$
BEGIN
    IF (SELECT count(*) FROM accounts) < 120 THEN
        RAISE EXCEPTION 'accounts minimum not met';
    END IF;
    IF (SELECT count(*) FROM shops) < 18 THEN
        RAISE EXCEPTION 'shops minimum not met';
    END IF;
    IF (SELECT count(*) FROM products) < 90 THEN
        RAISE EXCEPTION 'products minimum not met';
    END IF;
    IF (SELECT count(*) FROM conversations) < 40 THEN
        RAISE EXCEPTION 'conversations minimum not met';
    END IF;
    IF (SELECT count(*) FROM messages) < 420 THEN
        RAISE EXCEPTION 'messages minimum not met';
    END IF;
    IF (SELECT count(*) FROM transactions) < 100 THEN
        RAISE EXCEPTION 'transactions minimum not met';
    END IF;
END $$;

ROLLBACK;
```

Append these concrete invariant queries inside named `DO` blocks; each query raises when its `EXISTS` predicate returns a row:

```sql
-- Parent timestamps
SELECT 1 FROM login_events e JOIN accounts a ON a.id = e.account_id
 WHERE e.occurred_at < a.created_at LIMIT 1;
SELECT 1 FROM payment_attempts e JOIN transactions t ON t.id = e.transaction_id
 WHERE e.occurred_at < t.created_at LIMIT 1;
SELECT 1 FROM delivery_events e JOIN transactions t ON t.id = e.transaction_id
 WHERE e.occurred_at < t.created_at LIMIT 1;
SELECT 1 FROM refunds e JOIN transactions t ON t.id = e.transaction_id
 WHERE e.requested_at < t.created_at OR e.completed_at < e.requested_at LIMIT 1;
SELECT 1 FROM disputes e JOIN transactions t ON t.id = e.transaction_id
 WHERE e.created_at < t.created_at OR e.resolved_at < e.created_at LIMIT 1;

-- Conversation membership and review consistency
SELECT 1 FROM messages m
 WHERE NOT EXISTS (
   SELECT 1 FROM conversation_participants p
    WHERE p.conversation_id = m.conversation_id
      AND p.account_id = m.sender_account_id
 ) LIMIT 1;
SELECT 1 FROM reviews r JOIN transactions t ON t.id = r.transaction_id
 WHERE r.product_id <> t.product_id OR r.reviewer_account_id <> t.buyer_account_id LIMIT 1;

-- No visible future messages; repeat with each view's timestamp column
SELECT 1 FROM visible_messages v CROSS JOIN simulation_state s
 WHERE v.occurred_at > s.simulation_time LIMIT 1;

-- Forbidden marketplace columns
SELECT 1 FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name IN (
     'accounts', 'login_events', 'shops', 'products', 'conversations',
     'messages', 'transactions', 'payment_attempts', 'refunds', 'disputes'
   )
   AND column_name IN ('is_fraud', 'fraud_type', 'fraud_role', 'expected_detection')
 LIMIT 1;
```

For the visible-view checks, explicitly query `visible_account_status_events.occurred_at`, `visible_login_events.occurred_at`, `visible_account_security_events.occurred_at`, `visible_messages.occurred_at`, `visible_product_price_events.occurred_at`, `visible_product_status_events.occurred_at`, `visible_transaction_status_events.occurred_at`, `visible_payment_attempts.occurred_at`, `visible_delivery_events.occurred_at`, `visible_refunds.requested_at`, `visible_disputes.created_at`, and `visible_report_records.created_at`.

- [ ] **Step 2: Verify the tests fail on the current database definition**

Run:

```bash
docker compose config
docker compose down -v
docker compose up -d postgres
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -v ON_ERROR_STOP=1 -f /workspace/environment/tests/integrity.sql
```

If the test path is not yet mounted, run:

```bash
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -v ON_ERROR_STOP=1 < environment/tests/integrity.sql
```

Expected: nonzero exit with `missing required tables`.

- [ ] **Step 3: Commit the red test**

```bash
git add environment/tests/integrity.sql
git commit -m "test: define environment database invariants"
```

### Task 2: Replace the incomplete marketplace schema

**Files:**
- Modify: `environment/schema.sql`

**Interfaces:**
- Consumes: repository-compatible table and column names documented in the spec.
- Produces: all marketplace tables, constraints, indexes, replay views, and time-control SQL functions consumed by Tasks 3 and 4.

- [ ] **Step 1: Add the normalized tables while retaining compatibility columns**

Define the tables in foreign-key order. Preserve `accounts.id`, `login_events.id`, and all fields selected by existing `system-tools`. Use constraints with this form:

```sql
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    account_type TEXT NOT NULL CHECK (account_type IN ('buyer', 'seller', 'both')),
    country_code CHAR(2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'restricted', 'banned')),
    activity_score DOUBLE PRECISION,
    kyc_status TEXT NOT NULL CHECK (kyc_status IN ('unverified', 'pending', 'verified', 'rejected')),
    bot_check_score DOUBLE PRECISION CHECK (bot_check_score BETWEEN 0 AND 1),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    fingerprint_hash TEXT NOT NULL UNIQUE,
    device_type TEXT NOT NULL CHECK (device_type IN ('mobile', 'desktop', 'tablet')),
    os_family TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

Use `TEXT` primary keys, `TIMESTAMPTZ`, `NUMERIC(14,2)`, three-character currencies, foreign keys, and stable `CHECK` values throughout. Retain `cases`, `entities`, `relationships`, and `case_entities` after marketplace tables.

- [ ] **Step 2: Add replay state, functions, and views**

Create a one-row state table and functions:

```sql
CREATE TABLE simulation_state (
    singleton_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
    simulation_time TIMESTAMPTZ NOT NULL,
    initial_time TIMESTAMPTZ NOT NULL,
    scenario_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE FUNCTION advance_simulation_time(delta INTERVAL)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
DECLARE new_time TIMESTAMPTZ;
BEGIN
    IF delta <= INTERVAL '0 seconds' THEN
        RAISE EXCEPTION 'delta must be positive';
    END IF;
    UPDATE simulation_state
       SET simulation_time = simulation_time + delta,
           updated_at = simulation_time + delta
     WHERE singleton_id = 1
     RETURNING simulation_time INTO new_time;
    RETURN new_time;
END;
$$;
```

Implement `set_simulation_time`, `reset_simulation`, and all specified `visible_*` views using the event's actual time column (`occurred_at`, `requested_at`, or `created_at`).

- [ ] **Step 3: Add indexes and run schema initialization**

Add indexes for every foreign key plus common compound lookups such as `(account_id, occurred_at DESC)`, `(conversation_id, occurred_at)`, `(product_id, occurred_at DESC)`, and `(transaction_id, occurred_at)`.

Run the clean-volume startup again. Expected: schema initialization succeeds; integrity still fails only on row-count or seed invariants.

- [ ] **Step 4: Commit the schema**

```bash
git add environment/schema.sql
git commit -m "feat: define marketplace environment schema"
```

### Task 3: Generate the normal marketplace baseline in SQL

**Files:**
- Modify: `environment/seed.sql`

**Interfaces:**
- Consumes: table definitions from Task 2.
- Produces: deterministic normal accounts, access events, shops, products, conversations, messages, transactions, and post-transaction events.

- [ ] **Step 1: Write deterministic baseline inserts**

Use fixed timestamp arithmetic and `generate_series`, not randomness or `NOW()`:

```sql
WITH account_rows AS (
    SELECT
        n,
        'ACC-' || lpad(n::text, 4, '0') AS id,
        TIMESTAMPTZ '2026-06-01 00:00:00+08' + n * INTERVAL '2 hours' AS created_at
    FROM generate_series(1, 120) AS n
)
INSERT INTO accounts (
    id, account_type, country_code, created_at, status,
    activity_score, kyc_status, bot_check_score, attributes
)
SELECT
    id,
    CASE WHEN n % 10 = 0 THEN 'both' WHEN n % 4 = 0 THEN 'seller' ELSE 'buyer' END,
    CASE WHEN n % 12 = 0 THEN 'JP' ELSE 'TW' END,
    created_at,
    'active',
    ((n * 17) % 70)::double precision / 100,
    CASE WHEN n % 9 = 0 THEN 'pending' ELSE 'verified' END,
    ((n * 7) % 30)::double precision / 100,
    jsonb_build_object('segment', CASE WHEN n % 5 = 0 THEN 'returning' ELSE 'standard' END)
FROM account_rows;
```

Use these exact deterministic ranges and mappings:

- devices: `generate_series(1, 70)`, ID `DEV-####`, fingerprint `sha256-demo-device-####`, type selected by `n % 3`, creation at account epoch plus `n` hours;
- login events: `generate_series(1, 240)`, ID `LOG-####`, account `((n - 1) % 120) + 1`, device `((n - 1) % 70) + 1`, documentation IP blocks `192.0.2.0/24`, `198.51.100.0/24`, and `203.0.113.0/24`, with event time at least one day after both parents;
- shops: `generate_series(1, 18)`, ID `SHOP-###`, owner accounts `ACC-0004`, `ACC-0008`, through `ACC-0072`;
- products: `generate_series(1, 90)`, ID `PROD-####`, shop `((n - 1) % 18) + 1`, seller copied from that shop, fixed five-title and six-category arrays;
- conversations: `generate_series(1, 40)`, ID `CONV-###`, shop and transaction context derived by modulo after those parent rows exist;
- participants: exactly one seller and one buyer per conversation, with buyer `ACC-` IDs `0081` through `0120` cycling over 40 conversations;
- baseline messages: `generate_series(1, 420)`, ID `MSG-####`, conversation `((n - 1) % 40) + 1`, alternating buyer/seller participant, event time `2026-08-01 09:00:00+08 + n * 20 minutes`, and text chosen from ten fixed ordinary-commerce messages by modulo;
- transactions: `generate_series(1, 100)`, ID `TXN-####`, product `((n - 1) % 90) + 1`, seller copied from product, buyer cycling through `ACC-0081` to `ACC-0120`, quantity `(n % 3) + 1`, and amount derived from the latest seeded product price.

Insert rows in this order: accounts, account status events, devices, login/security events, shops, products, product price/status events, transactions, transaction status/payment/delivery events, conversations, participants, messages/attachments, refunds/disputes/reports, then reviews.

- [ ] **Step 2: Add normal payment, delivery, review, and refund histories**

For each transaction, insert created and terminal status events. Add successful payments and deliveries for the majority, deterministic declines followed by success for a minority, valid reviews only after delivery, and ordinary refunds for a small subset.

- [ ] **Step 3: Verify count and temporal tests move from red to green**

Recreate the volume and run `integrity.sql`. Expected: minimum counts and normal-path temporal checks pass; suspicious/hard-negative coverage checks added in Task 4 are not present yet.

- [ ] **Step 4: Commit the normal seed**

```bash
git add environment/seed.sql
git commit -m "feat: seed normal marketplace activity"
```

### Task 4: Inject hard negatives and suspicious journeys

**Files:**
- Modify: `environment/seed.sql`
- Modify: `environment/tests/integrity.sql`

**Interfaces:**
- Consumes: normal baseline IDs and the Cofacts-derived language strategy in the spec.
- Produces: ten unlabeled suspicious multi-table journeys and at least twenty legitimate hard-negative patterns.

- [ ] **Step 1: Add failing journey-shape assertions**

Assert on observable row structures rather than fraud labels. Examples:

```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM account_security_events s
          JOIN login_events l ON l.account_id = s.account_id
         WHERE s.event_type = 'password_reset'
           AND l.success
           AND l.country_code <> (SELECT a.country_code FROM accounts a WHERE a.id = l.account_id)
           AND l.occurred_at BETWEEN s.occurred_at AND s.occurred_at + INTERVAL '2 hours'
    ) THEN
        RAISE EXCEPTION 'missing account-takeover-shaped journey';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM refunds r
          JOIN disputes d ON d.transaction_id = r.transaction_id
         WHERE r.requested_at <= d.created_at
    ) THEN
        RAISE EXCEPTION 'missing refund-dispute journey';
    END IF;
END $$;
```

Run against the normal baseline. Expected: nonzero exit with a missing-journey exception.

- [ ] **Step 2: Add explicit hard-negative conversations and events**

Append exactly 20 hard-negative scenarios with stable IDs `HN-01` through `HN-20` distributed as follows:

- `HN-01`–`HN-04`: four ordinary conversations linking to `https://help.marketplace.test` or `https://shipping.marketplace.test`;
- `HN-05`–`HN-08`: four discussions mentioning bank transfer while explicitly keeping payment inside the platform;
- `HN-09`–`HN-12`: four successful travel logins from JP or SG followed by a normal TW login from the same device;
- `HN-13`–`HN-16`: four shops receiving five paid orders within one hour during a documented flash sale;
- `HN-17`–`HN-18`: two declined payment attempts followed by successful authorization on the same device and IP;
- `HN-19`–`HN-20`: two delivered transactions with a completed refund and no dispute.

Use only existing normal accounts and `HN-*` identifiers in non-label text attributes such as campaign/reference IDs; do not add a fraud classification field.

- [ ] **Step 3: Add ten explicit suspicious journeys**

Append two journeys for each of the five specified patterns. Use fictional text adapted from the Cofacts ecommerce-scam language pool, for example off-platform verification, fake customer-service escalation, payment instrument churn, empty-package seller behavior, and repeated refund-plus-dispute behavior. Store only observable facts and events; do not insert labels or scores.

- [ ] **Step 4: Verify the full data integrity suite passes**

Recreate the volume and run the SQL test. Expected: all assertions pass with exit code 0.

- [ ] **Step 5: Commit injected data and assertions**

```bash
git add environment/seed.sql environment/tests/integrity.sql
git commit -m "feat: add suspicious marketplace journeys"
```

### Task 5: Integrate and document the database

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`
- Create: `environment/README.md`
- Delete: `.DS_Store`
- Delete: `shared/.DS_Store`
- Delete: `shared/schemas/.DS_Store`

**Interfaces:**
- Consumes: schema, seed, and test paths from Tasks 1–4.
- Produces: documented local startup and repeatable test commands while preserving existing Compose services.

- [ ] **Step 1: Mount the SQL integrity test read-only**

Add this mount to the existing PostgreSQL service without changing other service source code:

```yaml
- ./environment/tests:/workspace/environment/tests:ro
```

Keep PostgreSQL 16 Alpine, the named volume, schema-before-seed initialization order, existing service dependencies, and environment-variable defaults.

- [ ] **Step 2: Write Environment usage documentation**

Document:

```bash
cp .env.example .env
docker compose up -d
docker compose ps
docker compose logs postgres
docker compose exec -T postgres \
  psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" \
  -v ON_ERROR_STOP=1 -f /workspace/environment/tests/integrity.sql
```

Include container and host connection strings, visible-view guidance, simulation functions, restart behavior, clean reseeding with `docker compose down -v`, the destructive-volume warning, and Cofacts CC BY-SA 4.0 attribution.

- [ ] **Step 3: Add only a root README link and clean ignored artifacts**

Append an Environment Database link to the root README without rewriting existing service documentation. Confirm `.gitignore` covers `.env`, `.DS_Store`, `__pycache__/`, `*.pyc`, and `.pytest_cache/`, then remove only the three tracked `.DS_Store` files.

- [ ] **Step 4: Validate Compose and documentation commands**

Run `docker compose config` and each documented read-only status/test command. Expected: config exits 0 and the integrity command passes.

- [ ] **Step 5: Commit integration and docs**

```bash
git add docker-compose.yml .env.example .gitignore README.md environment/README.md
git add -u .DS_Store shared/.DS_Store shared/schemas/.DS_Store
git commit -m "docs: add environment database workflow"
```

### Task 6: Perform clean-volume and persistence verification

**Files:**
- Verify only; modify the smallest owning file if a test exposes a defect.

**Interfaces:**
- Consumes: the complete Environment database deliverable.
- Produces: evidence that initialization, replay, integrity, and persistence behave as documented.

- [ ] **Step 1: Run static checks**

```bash
git diff --check main...HEAD
docker compose config
git ls-files | grep -E '(^|/)\.DS_Store$' && exit 1 || true
grep -RniE 'is_fraud|fraud_type|fraud_role|expected_detection' environment/schema.sql environment/seed.sql && exit 1 || true
```

Expected: all commands exit 0 with no forbidden fields or tracked `.DS_Store` files.

- [ ] **Step 2: Verify a clean initialization and health**

```bash
docker compose down -v
docker compose up -d
docker compose ps
docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -v ON_ERROR_STOP=1 -f /workspace/environment/tests/integrity.sql
```

Expected: PostgreSQL reports healthy/accepting connections and integrity SQL exits 0.

- [ ] **Step 3: Verify replay hides future data**

Record counts from a base event table and its `visible_*` view, advance time, and confirm only the visible count increases:

```bash
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -v ON_ERROR_STOP=1 -c "SELECT count(*) AS all_messages FROM messages; SELECT count(*) AS visible_messages FROM visible_messages; SELECT advance_simulation_time(INTERVAL '7 days'); SELECT count(*) AS advanced_visible_messages FROM visible_messages;"
```

- [ ] **Step 4: Verify restart persistence**

```bash
docker compose restart postgres
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -Atc "SELECT count(*) FROM accounts;"
```

Expected: account count remains at least 120.

- [ ] **Step 5: Re-run a clean rebuild**

```bash
docker compose down -v
docker compose up -d
docker compose exec -T postgres psql -U "${POSTGRES_USER:-fraud}" -d "${POSTGRES_DB:-fraud_intelligence}" -v ON_ERROR_STOP=1 -f /workspace/environment/tests/integrity.sql
```

Expected: clean initialization and integrity test pass again.

- [ ] **Step 6: Inspect final branch state**

```bash
git status --short --branch
git diff --stat main...HEAD
git log --oneline --decorate main..HEAD
```

Expected: clean working tree, only scoped files changed, and no push or merge performed.
