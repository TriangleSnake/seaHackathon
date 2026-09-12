CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'restricted', 'banned')),
    activity_score DOUBLE PRECISION,
    kyc_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (kyc_status IN ('unverified', 'pending', 'verified', 'rejected')),
    bot_check_score DOUBLE PRECISION CHECK (bot_check_score BETWEEN 0 AND 1),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS login_events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    ip_address INET NOT NULL,
    device_id TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS login_events_account_idx ON login_events(account_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS login_events_ip_idx ON login_events(ip_address, occurred_at DESC);
CREATE INDEX IF NOT EXISTS login_events_device_idx ON login_events(device_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS shops (
    id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL REFERENCES accounts(id),
    name TEXT,
    status TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL REFERENCES shops(id),
    seller_account_id TEXT NOT NULL REFERENCES accounts(id),
    title TEXT NOT NULL,
    description TEXT,
    image_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    price NUMERIC(14, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    buyer_account_id TEXT NOT NULL REFERENCES accounts(id),
    seller_account_id TEXT NOT NULL REFERENCES accounts(id),
    product_id TEXT REFERENCES products(id),
    payment_method TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    amount NUMERIC(14, 2),
    status TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender_account_id TEXT NOT NULL REFERENCES accounts(id),
    recipient_account_id TEXT REFERENCES accounts(id),
    text TEXT,
    image_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS report_records (
    id TEXT PRIMARY KEY,
    target_account_id TEXT NOT NULL REFERENCES accounts(id),
    type TEXT NOT NULL CHECK (type IN ('report', 'violation', 'enforcement', 'dispute')),
    reason TEXT,
    status TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    risk_score DOUBLE PRECISION CHECK (risk_score BETWEEN 0 AND 1),
    trigger_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS cases_subject_idx ON cases(subject_type, subject_id, created_at DESC);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    type TEXT NOT NULL,
    value TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    UNIQUE (source_id, target_id, type)
);
CREATE INDEX IF NOT EXISTS relationships_source_idx ON relationships(source_id);
CREATE INDEX IF NOT EXISTS relationships_target_idx ON relationships(target_id);

CREATE TABLE IF NOT EXISTS case_entities (
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id),
    role TEXT NOT NULL DEFAULT 'related',
    PRIMARY KEY (case_id, entity_id)
);
