CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    account_type TEXT NOT NULL CHECK (account_type IN ('buyer', 'seller', 'both')),
    country_code CHAR(2) NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'restricted', 'banned')),
    activity_score DOUBLE PRECISION CHECK (activity_score IS NULL OR activity_score >= 0),
    kyc_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (kyc_status IN ('unverified', 'pending', 'verified', 'rejected')),
    bot_check_score DOUBLE PRECISION CHECK (bot_check_score BETWEEN 0 AND 1),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE account_status_events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    status TEXT NOT NULL CHECK (status IN ('active', 'restricted', 'banned')),
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX account_status_events_account_time_idx
    ON account_status_events(account_id, occurred_at DESC);
CREATE INDEX account_status_events_time_idx ON account_status_events(occurred_at);

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    fingerprint_hash TEXT NOT NULL UNIQUE,
    device_type TEXT NOT NULL CHECK (device_type IN ('mobile', 'desktop', 'tablet')),
    os_family TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE login_events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    device_id TEXT REFERENCES devices(id),
    ip_address INET NOT NULL,
    country_code CHAR(2) NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    region_code TEXT,
    success BOOLEAN NOT NULL,
    auth_method TEXT NOT NULL CHECK (auth_method IN ('password', 'passkey', 'oauth', 'mfa')),
    occurred_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX login_events_account_time_idx ON login_events(account_id, occurred_at DESC);
CREATE INDEX login_events_ip_time_idx ON login_events(ip_address, occurred_at DESC);
CREATE INDEX login_events_device_time_idx ON login_events(device_id, occurred_at DESC);
CREATE INDEX login_events_time_idx ON login_events(occurred_at);

CREATE TABLE account_security_events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'password_reset', 'email_changed', 'phone_changed', 'kyc_changed',
        'mfa_enabled', 'mfa_disabled'
    )),
    occurred_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX account_security_events_account_time_idx
    ON account_security_events(account_id, occurred_at DESC);
CREATE INDEX account_security_events_time_idx ON account_security_events(occurred_at);

CREATE TABLE shops (
    id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL REFERENCES accounts(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'closed')),
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX shops_owner_idx ON shops(owner_account_id);

CREATE TABLE products (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL REFERENCES shops(id),
    seller_account_id TEXT NOT NULL REFERENCES accounts(id),
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    image_urls JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(image_urls) = 'array'),
    price NUMERIC(14,2) CHECK (price IS NULL OR price >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'TWD' CHECK (currency ~ '^[A-Z]{3}$'),
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX products_shop_idx ON products(shop_id);
CREATE INDEX products_seller_idx ON products(seller_account_id);
CREATE INDEX products_category_idx ON products(category);

CREATE TABLE product_images (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    image_url TEXT NOT NULL,
    image_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (product_id, image_hash)
);
CREATE INDEX product_images_product_idx ON product_images(product_id);

CREATE TABLE product_price_events (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    price NUMERIC(14,2) NOT NULL CHECK (price >= 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX product_price_events_product_time_idx
    ON product_price_events(product_id, occurred_at DESC);
CREATE INDEX product_price_events_time_idx ON product_price_events(occurred_at);

CREATE TABLE product_status_events (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'sold_out', 'removed')),
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX product_status_events_product_time_idx
    ON product_status_events(product_id, occurred_at DESC);
CREATE INDEX product_status_events_time_idx ON product_status_events(occurred_at);

CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    buyer_account_id TEXT NOT NULL REFERENCES accounts(id),
    seller_account_id TEXT NOT NULL REFERENCES accounts(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    payment_method TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status TEXT NOT NULL CHECK (status IN (
        'created', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded'
    )),
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX transactions_buyer_time_idx ON transactions(buyer_account_id, created_at DESC);
CREATE INDEX transactions_seller_time_idx ON transactions(seller_account_id, created_at DESC);
CREATE INDEX transactions_product_time_idx ON transactions(product_id, created_at DESC);

CREATE TABLE transaction_status_events (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    status TEXT NOT NULL CHECK (status IN (
        'created', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded'
    )),
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX transaction_status_events_transaction_time_idx
    ON transaction_status_events(transaction_id, occurred_at);
CREATE INDEX transaction_status_events_time_idx ON transaction_status_events(occurred_at);

CREATE TABLE payment_attempts (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    payer_account_id TEXT NOT NULL REFERENCES accounts(id),
    payment_method TEXT NOT NULL CHECK (payment_method IN (
        'credit_card', 'debit_card', 'wallet', 'bank_transfer', 'cash_on_delivery'
    )),
    payment_instrument_hash TEXT NOT NULL,
    amount NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    currency CHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    status TEXT NOT NULL CHECK (status IN ('initiated', 'authorized', 'declined', 'failed')),
    failure_code TEXT,
    device_id TEXT REFERENCES devices(id),
    ip_address INET,
    occurred_at TIMESTAMPTZ NOT NULL,
    CHECK ((status IN ('declined', 'failed')) OR failure_code IS NULL)
);
CREATE INDEX payment_attempts_transaction_time_idx
    ON payment_attempts(transaction_id, occurred_at);
CREATE INDEX payment_attempts_payer_time_idx
    ON payment_attempts(payer_account_id, occurred_at DESC);
CREATE INDEX payment_attempts_instrument_idx ON payment_attempts(payment_instrument_hash);
CREATE INDEX payment_attempts_device_idx ON payment_attempts(device_id);
CREATE INDEX payment_attempts_ip_idx ON payment_attempts(ip_address);
CREATE INDEX payment_attempts_time_idx ON payment_attempts(occurred_at);

CREATE TABLE delivery_events (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    status TEXT NOT NULL CHECK (status IN (
        'label_created', 'picked_up', 'in_transit', 'delivered', 'delivery_failed', 'returned'
    )),
    occurred_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX delivery_events_transaction_time_idx
    ON delivery_events(transaction_id, occurred_at);
CREATE INDEX delivery_events_time_idx ON delivery_events(occurred_at);

CREATE TABLE refunds (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    requester_account_id TEXT NOT NULL REFERENCES accounts(id),
    reason TEXT NOT NULL,
    amount NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    status TEXT NOT NULL CHECK (status IN ('requested', 'approved', 'rejected', 'completed')),
    requested_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CHECK (completed_at IS NULL OR completed_at >= requested_at)
);
CREATE INDEX refunds_transaction_time_idx ON refunds(transaction_id, requested_at);
CREATE INDEX refunds_requester_time_idx ON refunds(requester_account_id, requested_at DESC);
CREATE INDEX refunds_requested_time_idx ON refunds(requested_at);

CREATE TABLE disputes (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    opened_by_account_id TEXT NOT NULL REFERENCES accounts(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'under_review', 'resolved_buyer', 'resolved_seller', 'closed')),
    created_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    CHECK (resolved_at IS NULL OR resolved_at >= created_at)
);
CREATE INDEX disputes_transaction_time_idx ON disputes(transaction_id, created_at);
CREATE INDEX disputes_opener_time_idx ON disputes(opened_by_account_id, created_at DESC);
CREATE INDEX disputes_created_time_idx ON disputes(created_at);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    shop_id TEXT REFERENCES shops(id),
    transaction_id TEXT REFERENCES transactions(id),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX conversations_shop_idx ON conversations(shop_id);
CREATE INDEX conversations_transaction_idx ON conversations(transaction_id);

CREATE TABLE conversation_participants (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    participant_role TEXT NOT NULL CHECK (participant_role IN ('buyer', 'seller', 'support')),
    joined_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (conversation_id, account_id)
);
CREATE INDEX conversation_participants_account_idx ON conversation_participants(account_id);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    sender_account_id TEXT NOT NULL REFERENCES accounts(id),
    recipient_account_id TEXT REFERENCES accounts(id),
    message_type TEXT NOT NULL CHECK (message_type IN ('text', 'image', 'system')),
    text TEXT,
    image_urls JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(image_urls) = 'array'),
    urls JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(urls) = 'array'),
    reply_to_message_id TEXT REFERENCES messages(id),
    created_at TIMESTAMPTZ NOT NULL,
    occurred_at TIMESTAMPTZ GENERATED ALWAYS AS (created_at) STORED,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (reply_to_message_id IS NULL OR reply_to_message_id <> id),
    CHECK (message_type <> 'text' OR text IS NOT NULL)
);
CREATE INDEX messages_conversation_time_idx ON messages(conversation_id, created_at);
CREATE INDEX messages_sender_time_idx ON messages(sender_account_id, created_at DESC);
CREATE INDEX messages_reply_idx ON messages(reply_to_message_id);
CREATE INDEX messages_time_idx ON messages(created_at);

CREATE TABLE message_attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    attachment_type TEXT NOT NULL CHECK (attachment_type IN ('image', 'url', 'file')),
    resource_url TEXT NOT NULL,
    mime_type TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX message_attachments_message_idx ON message_attachments(message_id);

CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    transaction_id TEXT NOT NULL UNIQUE REFERENCES transactions(id),
    reviewer_account_id TEXT NOT NULL REFERENCES accounts(id),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX reviews_product_time_idx ON reviews(product_id, created_at DESC);
CREATE INDEX reviews_reviewer_time_idx ON reviews(reviewer_account_id, created_at DESC);

CREATE TABLE report_records (
    id TEXT PRIMARY KEY,
    reporter_account_id TEXT REFERENCES accounts(id),
    target_account_id TEXT NOT NULL REFERENCES accounts(id),
    target_type TEXT NOT NULL DEFAULT 'account'
        CHECK (target_type IN ('account', 'shop', 'product', 'transaction', 'message')),
    target_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('report', 'violation', 'enforcement', 'dispute')),
    reason TEXT,
    status TEXT CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX report_records_reporter_time_idx
    ON report_records(reporter_account_id, created_at DESC);
CREATE INDEX report_records_target_account_time_idx
    ON report_records(target_account_id, created_at DESC);
CREATE INDEX report_records_target_idx ON report_records(target_type, target_id, created_at DESC);
CREATE INDEX report_records_created_time_idx ON report_records(created_at);

CREATE TABLE cases (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    risk_score DOUBLE PRECISION CHECK (risk_score BETWEEN 0 AND 1),
    trigger_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX cases_subject_idx ON cases(subject_type, subject_id, created_at DESC);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE relationships (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    type TEXT NOT NULL,
    value TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    CHECK (source_id <> target_id),
    CHECK (last_seen_at IS NULL OR first_seen_at IS NULL OR last_seen_at >= first_seen_at),
    UNIQUE (source_id, target_id, type)
);
CREATE INDEX relationships_source_idx ON relationships(source_id);
CREATE INDEX relationships_target_idx ON relationships(target_id);

CREATE TABLE case_entities (
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id),
    role TEXT NOT NULL DEFAULT 'related',
    PRIMARY KEY (case_id, entity_id)
);
CREATE INDEX case_entities_entity_idx ON case_entities(entity_id);

CREATE TABLE simulation_state (
    singleton_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
    simulation_time TIMESTAMPTZ NOT NULL,
    initial_time TIMESTAMPTZ NOT NULL,
    scenario_name TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (simulation_time >= initial_time)
);

CREATE OR REPLACE FUNCTION set_simulation_time(new_time TIMESTAMPTZ)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
DECLARE
    result TIMESTAMPTZ;
BEGIN
    IF new_time IS NULL THEN
        RAISE EXCEPTION 'simulation time must not be null';
    END IF;

    UPDATE simulation_state
       SET simulation_time = new_time,
           updated_at = new_time
     WHERE singleton_id = 1
     RETURNING simulation_time INTO result;

    IF result IS NULL THEN
        RAISE EXCEPTION 'simulation state is not initialized';
    END IF;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION advance_simulation_time(delta INTERVAL)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
DECLARE
    result TIMESTAMPTZ;
BEGIN
    IF delta IS NULL OR delta <= INTERVAL '0 seconds' THEN
        RAISE EXCEPTION 'delta must be positive';
    END IF;

    UPDATE simulation_state
       SET simulation_time = simulation_time + delta,
           updated_at = simulation_time + delta
     WHERE singleton_id = 1
     RETURNING simulation_time INTO result;

    IF result IS NULL THEN
        RAISE EXCEPTION 'simulation state is not initialized';
    END IF;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION reset_simulation()
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
AS $$
DECLARE
    result TIMESTAMPTZ;
BEGIN
    UPDATE simulation_state
       SET simulation_time = initial_time,
           updated_at = initial_time
     WHERE singleton_id = 1
     RETURNING simulation_time INTO result;

    IF result IS NULL THEN
        RAISE EXCEPTION 'simulation state is not initialized';
    END IF;
    RETURN result;
END;
$$;

CREATE VIEW visible_account_status_events AS
SELECT e.*
  FROM account_status_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_login_events AS
SELECT e.*
  FROM login_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_account_security_events AS
SELECT e.*
  FROM account_security_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_messages AS
SELECT m.*
  FROM messages m
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND m.created_at <= s.simulation_time;

CREATE VIEW visible_product_price_events AS
SELECT e.*
  FROM product_price_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_product_status_events AS
SELECT e.*
  FROM product_status_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_transaction_status_events AS
SELECT e.*
  FROM transaction_status_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_payment_attempts AS
SELECT e.*
  FROM payment_attempts e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_delivery_events AS
SELECT e.*
  FROM delivery_events e
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND e.occurred_at <= s.simulation_time;

CREATE VIEW visible_refunds AS
SELECT r.*
  FROM refunds r
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND r.requested_at <= s.simulation_time;

CREATE VIEW visible_disputes AS
SELECT d.*
  FROM disputes d
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND d.created_at <= s.simulation_time;

CREATE VIEW visible_report_records AS
SELECT r.*
  FROM report_records r
 CROSS JOIN simulation_state s
 WHERE s.singleton_id = 1 AND r.created_at <= s.simulation_time;

-- Runtime control-plane state shared by Patrol, Association, and Dashboard.
CREATE OR REPLACE VIEW visible_products AS
SELECT p.id, p.shop_id, p.seller_account_id, p.title, p.description, p.category,
       p.image_urls, COALESCE(e.price, p.price) AS price,
       COALESCE(e.currency, p.currency) AS currency, p.created_at, p.attributes
FROM products p CROSS JOIN simulation_state s
LEFT JOIN LATERAL (
    SELECT price, currency FROM product_price_events
    WHERE product_id = p.id AND occurred_at <= s.simulation_time
    ORDER BY occurred_at DESC, id DESC LIMIT 1
) e ON true
WHERE s.singleton_id = 1 AND p.created_at <= s.simulation_time;

CREATE TABLE agent_jobs (
    job_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL CHECK (agent IN ('patrol', 'association')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    request JSONB NOT NULL,
    state JSONB NOT NULL,
    callback_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_jobs_agent_updated_idx ON agent_jobs(agent, updated_at DESC);

CREATE TABLE agent_policies (
    agent TEXT NOT NULL CHECK (agent IN ('patrol', 'association')),
    strategy TEXT NOT NULL,
    version TEXT NOT NULL,
    document JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT false,
    source TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'evolution')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent, strategy, version)
);
CREATE UNIQUE INDEX agent_policies_one_active_idx
    ON agent_policies(agent, strategy) WHERE active;

CREATE TABLE patrol_schedules (
    strategy TEXT PRIMARY KEY CHECK (strategy IN ('exploit', 'explore')),
    enabled BOOLEAN NOT NULL DEFAULT false,
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 60),
    scope JSONB NOT NULL DEFAULT '{"subject_types": []}'::jsonb,
    next_run_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO patrol_schedules(strategy, enabled, interval_seconds) VALUES
    ('exploit', false, 900),
    ('explore', false, 86400);
