# Environment Database Design

## Goal

Build a deterministic PostgreSQL marketplace environment that contains realistic normal activity, hard negatives, and injected suspicious journeys. The database is the observable world for other agents; it does not implement Detection, Investigation, Dashboard, an Environment API, or an Environment Agent.

The current repository is authoritative when it conflicts with the original standalone Environment brief. Existing `system-tools` source code and its database-facing column names remain compatible, but no new `system-tools` behavior is added.

## Scope

This change owns only the root Docker configuration, root Environment documentation links, shared Environment schema when required, and files under `environment/`. It does not modify source files under `services/` or `agentgateway/`, and it does not push or merge the branch.

The implementation will:

- expand the existing PostgreSQL schema into a normalized marketplace model;
- generate a repeatable normal baseline with seed `20260912`;
- derive a small, sanitized ecommerce-scam language pool from the local Cofacts snapshot;
- inject five categories of suspicious journeys and realistic hard negatives;
- provide simulation-time views and integrity tests;
- keep evaluator-only labels outside PostgreSQL.

## Repository Compatibility

The repository currently exposes `system-tools` queries against `accounts`, `login_events`, `report_records`, `cases`, `entities`, and `relationships`. Those tables and the columns used by the existing queries remain available. In particular:

- `accounts.id`, `accounts.status`, `accounts.activity_score`, `accounts.kyc_status`, `accounts.bot_check_score`, and `accounts.attributes` remain;
- `login_events.id`, `account_id`, `ip_address`, `device_id`, `occurred_at`, and `attributes` remain;
- `report_records`, `cases`, `entities`, `relationships`, and `case_entities` remain present;
- the existing Compose services are retained rather than replaced with a new application service.

New event tables become the authoritative time history for replay. Compatibility status columns remain current snapshots for existing tools. Injected journey ground truth is never written to compatibility tables such as `cases` and is only stored in the evaluator file.

## Database Model

All identifiers are readable `TEXT` values, timestamps are `TIMESTAMPTZ`, money is `NUMERIC(14,2)`, currencies are constrained three-character strings, and mutable categorical state uses `CHECK` constraints rather than PostgreSQL enums.

### Account and access

- `accounts`: existing compatible columns plus account type and country code.
- `account_status_events`: append-only active, restricted, and banned history.
- `devices`: normalized device fingerprint, type, OS family, and creation time.
- `login_events`: existing compatible columns plus country, region, success, and authentication method.
- `account_security_events`: password, identity, KYC, and MFA changes.

### Marketplace chat

- `conversations`: optional shop and transaction context.
- `conversation_participants`: account membership and buyer, seller, or support role.
- `messages`: existing compatible columns plus message type and reply relationship.
- `message_attachments`: normalized image, URL, and file resources.

Existing JSON URL/image columns stay for compatibility but normalized attachments are the queryable source for new data.

### Shops and products

- `shops`: existing compatible shop identity and owner.
- `products`: existing compatible product identity, seller, and descriptive fields.
- `product_images`: normalized images and hashes.
- `product_price_events`: append-only price history.
- `product_status_events`: draft, active, sold-out, and removed history.
- `reviews`: rating and text tied to a real product and transaction.

### Transactions and post-transaction activity

The repository term `transactions` is canonical rather than adding a parallel `orders` table.

- `transactions`: buyer, seller, product, quantity, amount, currency, and creation time.
- `transaction_status_events`: created, paid, shipped, delivered, cancelled, and refunded history.
- `payment_attempts`: instrument hash, device, IP, amount, currency, result, and optional failure code.
- `delivery_events`: shipment progress.
- `refunds`: request and optional completion.
- `disputes`: open and optional resolution history.
- `report_records`: retained and extended with reporter and generic target information while preserving existing query columns.

No complete card number, CVV, bank account, real identity, or real malicious destination is stored.

### Simulation and compatibility control-plane tables

- `simulation_state`: a single row containing current simulation time, initial time, scenario name, and update time.
- `cases`, `entities`, `relationships`, and `case_entities`: retained unchanged in purpose for repository compatibility; they are not used as labels for generated suspicious journeys.

Foreign-key, occurred-time, account, conversation, product, and transaction lookup indexes cover expected query paths.

## Time Replay

The seed contains the complete timeline, including events later than the initial simulation time. Consumers use `visible_*` views so future events remain hidden.

Views include:

- `visible_account_status_events`
- `visible_login_events`
- `visible_account_security_events`
- `visible_messages`
- `visible_product_price_events`
- `visible_product_status_events`
- `visible_transaction_status_events`
- `visible_payment_attempts`
- `visible_delivery_events`
- `visible_refunds`
- `visible_disputes`
- `visible_report_records`

Each view joins the singleton simulation row and filters on the relevant event timestamp. The database provides `set_simulation_time(TIMESTAMPTZ)`, `advance_simulation_time(INTERVAL)`, and `reset_simulation()` functions. Reset restores the initial timestamp recorded in `simulation_state`; time cannot advance outside the seeded timeline without an explicit set operation.

## Synthetic Data Generation

`environment/generate_seed.py` uses only the Python standard library and `random.Random(20260912)`. It writes deterministic SQL and evaluator-only JSON with stable ordering.

The baseline contains at least:

- 120 accounts;
- 18 shops;
- 90 products;
- 40 conversations;
- 420 messages;
- 100 transactions;
- associated devices, logins, security events, prices, statuses, payments, deliveries, refunds, disputes, reports, and reviews.

Most records form ordinary marketplace activity. At least 20 deliberately difficult normal cases cover legitimate external links, bank-transfer discussion without off-platform payment, travel-related country changes, legitimate order spikes, failed payments followed by success, and reasonable refunds.

Ten suspicious journeys are injected, two per category:

1. social engineering and chat phishing;
2. account takeover;
3. payment fraud;
4. seller fraud;
5. buyer and refund abuse.

Each journey spans multiple related tables and times rather than relying on a single keyword. Suspicious text does not use one repeated template.

## Cofacts Selection and Sanitization

The source snapshot is read from an explicit command-line path and is never copied wholesale into the repository. The inspected snapshot contains 294,085 articles, including 230,324 text articles. There are 19,584 active links to the Cofacts fraud category, 15,206 corresponding active text articles, and 2,011 articles that also contain ecommerce-context terms. Of those candidates, 1,154 have an active fact-check reply link.

`environment/filter_cofacts.py` streams the zipped CSV files with the Python standard library. A high-confidence candidate must satisfy all of these conditions:

1. `articles.articleType = TEXT`;
2. `articles.status = NORMAL`;
3. an active `article_categories` row links it to category `nD2n7nEBrIRcahlYwQoW` (`詐騙`);
4. its text contains at least one ecommerce-context term such as ordering, marketplace, payment, logistics, customer service, buyer, seller, or refund language;
5. it has an active `article_replies` link whose `replyType = RUMOR`.

`RUMOR` alone is insufficient because misinformation is broader than fraud. The filter emits only the bounded deterministic candidate sample needed by the generator.

Before any text is stored, the pipeline removes or replaces phone numbers, account-like digit sequences, email addresses, user identifiers, URLs, tracking identifiers, and named external destinations. URLs in generated messages use reserved `.test` or `.invalid` domains. Selected language is adapted into fictional buyer-seller conversations rather than presented as a verbatim LINE transcript.

The Environment README contains the Cofacts attribution required by its CC BY-SA 4.0 dataset card and documents the local-source command. The generated seed remains reproducible after the source-derived, sanitized candidate fixture is committed.

## Ground Truth Isolation

`environment/datasets/ground_truth.json` contains evaluator-only journey IDs, subject references, fraud category, involved roles, event IDs, and expected observation window. PostgreSQL initialization does not load or mount this file, and Compose does not expose it to other services.

Database tables do not add `is_fraud`, `fraud_type`, `fraud_role`, `expected_detection`, or new journey `risk_score` fields. The existing compatibility `cases.risk_score` column remains because repository tools already depend on that control-plane contract, but generated Environment journeys do not populate it.

The ground-truth file contains more explicitly normal and hard-negative cases than suspicious journeys.

## Files

- `docker-compose.yml`: retain the existing stack while making Environment initialization and test execution reproducible.
- `.env.example`: retain development-only sample values and document Environment defaults without adding secrets.
- `.gitignore`: retain current ignores and ensure generated caches are excluded.
- `README.md`: add only a concise link to the Environment instructions.
- `environment/schema.sql`: normalized schema, compatibility tables, constraints, indexes, views, and time-control functions.
- `environment/seed.sql`: deterministic generated dataset loaded after the schema.
- `environment/generate_seed.py`: normal baseline and journey injection generator.
- `environment/filter_cofacts.py`: streaming Cofacts candidate selection and sanitization.
- `environment/datasets/cofacts_ecommerce_scam.jsonl`: bounded sanitized source fixture with attribution metadata and no raw identifiers.
- `environment/datasets/ground_truth.json`: evaluator-only labels, never loaded into PostgreSQL.
- `environment/README.md`: setup, connections, replay, rebuild, tests, attribution, and isolation rules.
- `environment/tests/integrity.sql`: executable assertions that terminate with an error when invariants fail.
- `shared/schemas/environment.schema.json`: changed only where necessary to describe the repository-compatible normalized exchange model; Draft 2020-12 and common subject IDs remain intact.

Tracked `.DS_Store` files are removed; no other team files are deleted.

## Validation

The implementation follows test-first development. Static fixture and generator tests fail before generator implementation. Database integrity tests fail against the incomplete schema before the schema is extended.

Validation covers:

- deterministic generator output across repeated runs;
- Cofacts filter selection and redaction on small fixtures;
- JSON validity and absence of forbidden ground-truth fields in SQL;
- Compose configuration parsing;
- clean-volume PostgreSQL initialization;
- primary-key uniqueness and foreign-key integrity;
- event timestamps after parent creation times;
- message sender membership in its conversation;
- review-to-product and review-to-transaction consistency;
- simulation views hiding future rows;
- minimum row counts and all five evaluator journey types;
- normal and hard-negative ground truth outnumbering suspicious journeys;
- PostgreSQL health after restart and data persistence across restart;
- clean rebuild after removing the development volume.

When Docker is unavailable, all generator, static SQL, JSON, and Compose checks still run, and Docker-only checks are reported as unexecuted rather than passed.

## Error Handling and Reproducibility

Both Python scripts fail with a nonzero status and a concise error when required archives, headers, category links, or output invariants are missing. They never mutate the Hugging Face cache. Seed output is generated into repository files only after all in-memory referential and count checks pass.

SQL initialization uses `ON_ERROR_STOP` during tests, constraints reject invalid data, and integrity assertions raise exceptions with specific invariant names. Re-running the generator produces byte-identical output for the same source fixture and seed.

## Non-goals

- No FastAPI or other Environment application service.
- No new MCP server or `system-tools` feature.
- No Detection feature extraction or scoring.
- No Investigation, Dashboard, patrol, evaluator runtime, or model training.
- No push, merge, or changes to unrelated service implementations.
