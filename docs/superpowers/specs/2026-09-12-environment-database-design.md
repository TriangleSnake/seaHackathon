# Environment Dummy Database Design

## Goal

Deliver a self-contained PostgreSQL dummy database for a fictional marketplace. It contains a large normal baseline, hard negatives, and a small number of suspicious multi-event journeys. The deliverable is SQL and database documentation, not an application.

The current repository is authoritative. Existing database columns used by `system-tools` remain compatible, but this task does not modify or add any `system-tools`, API, MCP, Detection, Investigation, or Dashboard code.

## Deliverables

Only these project artifacts are created or updated:

- `environment/schema.sql`: tables, constraints, indexes, replay views, and time-control functions.
- `environment/seed.sql`: complete deterministic dummy dataset.
- `environment/tests/integrity.sql`: database integrity assertions.
- `environment/README.md`: startup, connection, replay, reset, rebuild, testing, and data-source notes.
- `docker-compose.yml`: only the changes needed to initialize and test the database while preserving existing services.
- `.env.example`, `.gitignore`, and root `README.md`: minimal supporting changes.

No Python generator, importer, filter, application container, ground-truth file, or runtime service is committed. Temporary local tooling may be used to inspect Cofacts and mechanically produce SQL, but it is not part of the repository deliverable.

Tracked `.DS_Store` files are removed; no other team files are deleted.

## Repository Compatibility

The existing `accounts`, `login_events`, `report_records`, `cases`, `entities`, `relationships`, and `case_entities` tables and the columns currently queried by `services/system-tools` remain available. Existing Compose services are retained.

New normalized event tables provide historical data for replay. Existing snapshot-style fields remain for backward compatibility. Suspicious journeys do not populate `cases.risk_score` or add fraud-answer fields to marketplace tables.

## Database Model

Identifiers are readable `TEXT` values. Times are `TIMESTAMPTZ`, money is `NUMERIC(14,2)`, currency is a constrained three-character string, and categorical values use `CHECK` constraints.

### Accounts and access

- `accounts`
- `account_status_events`
- `devices`
- `login_events`
- `account_security_events`

### Marketplace chat

- `conversations`
- `conversation_participants`
- `messages`
- `message_attachments`

### Shops and products

- `shops`
- `products`
- `product_images`
- `product_price_events`
- `product_status_events`
- `reviews`

### Transactions and post-transaction activity

The repository term `transactions` remains canonical.

- `transactions`
- `transaction_status_events`
- `payment_attempts`
- `delivery_events`
- `refunds`
- `disputes`
- `report_records`

### Simulation and compatibility tables

- `simulation_state`
- `cases`
- `entities`
- `relationships`
- `case_entities`

All relations use foreign keys. Common account, conversation, product, transaction, IP, device, and event-time query paths receive indexes. No real identity, complete card number, CVV, bank account, or live malicious URL is stored.

## Time Replay

The database stores the full event timeline, including events later than the initial simulation time. Consumers should query `visible_*` views, including visible login, security, message, price, product-status, transaction-status, payment, delivery, refund, dispute, and report events.

Each view filters its event timestamp against the singleton `simulation_state.simulation_time`. SQL functions provide:

- `set_simulation_time(TIMESTAMPTZ)`
- `advance_simulation_time(INTERVAL)`
- `reset_simulation()`

Reset restores the initial seed timestamp.

## Dummy Dataset

`environment/seed.sql` uses fixed IDs, values, and timestamps so a clean-volume rebuild always produces the same data. It contains at least:

- 120 accounts;
- 18 shops;
- 90 products;
- 40 conversations;
- 420 messages;
- 100 transactions;
- corresponding devices, logins, security events, price changes, product statuses, payments, deliveries, refunds, disputes, reports, and reviews.

The normal baseline is generated first. At least 20 hard negatives include legitimate external links, ordinary bank-transfer discussion, travel-related login-country changes, legitimate seller order spikes, payment retries, and reasonable refunds.

Ten suspicious journeys are injected afterward, two for each pattern:

1. chat phishing and social engineering;
2. account takeover;
3. payment fraud;
4. seller fraud;
5. buyer and refund abuse.

Each suspicious journey is observable through several related records and times. The database does not label rows as fraud, store expected detections, or expose a risk score for these injected journeys.

## Cofacts Use

The downloaded Cofacts snapshot is an offline source for realistic Taiwanese scam language. It is not copied into the project or loaded as a database table.

The inspected snapshot contains 294,085 articles, including 230,324 text articles. There are 19,584 active fraud-category links, 15,206 corresponding active text articles, 2,011 articles that also contain ecommerce-context terms, and 1,154 such candidates with active fact-check replies.

Candidate selection requires:

1. active text article;
2. active Cofacts `詐騙` category link;
3. ecommerce context such as marketplace, order, payment, logistics, customer service, buyer, seller, or refund language;
4. an active linked reply with `replyType = RUMOR`.

`RUMOR` alone is not treated as fraud. Selected language is manually bounded, redacted, and adapted into fictional marketplace conversations. Phone numbers, account-like digit sequences, emails, user IDs, tracking IDs, original URLs, and named destinations are removed or replaced. Generated URLs use `.test` or `.invalid`.

The Environment README includes Cofacts attribution and CC BY-SA 4.0 source information. No raw Cofacts archive or identifying source field is shipped in the database.

## Integrity Tests

`environment/tests/integrity.sql` exits nonzero if any invariant fails. It checks:

- primary-key uniqueness and foreign-key integrity;
- account creation before account events;
- transaction creation before payments, delivery, refunds, and disputes;
- refund completion not earlier than request;
- message senders are conversation participants;
- reviews match existing products and transactions;
- visible views hide future events;
- forbidden fraud-answer columns are absent from marketplace tables;
- minimum seed counts are met;
- normal and hard-negative activity outnumbers injected suspicious journeys by construction.

Static validation checks SQL formatting, deterministic literal timestamps, absence of real secrets, Compose parsing, and removal of tracked `.DS_Store` files. Docker validation covers clean initialization, PostgreSQL health, integrity SQL, restart persistence, and clean-volume rebuild. Docker-only checks are reported as unexecuted if Docker is unavailable.

## Non-goals

- No Python or application code in the final project changes.
- No API, MCP server, or `system-tools` feature.
- No model, classifier, feature extractor, or fraud-scoring logic.
- No Detection, Investigation, Dashboard, evaluator runtime, or agent implementation.
- No push, merge, or unrelated service changes.
