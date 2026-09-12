\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    missing_tables TEXT[];
    missing_views TEXT[];
BEGIN
    SELECT array_agg(name ORDER BY name)
      INTO missing_tables
      FROM unnest(ARRAY[
        'accounts', 'account_status_events', 'devices', 'login_events',
        'account_security_events', 'conversations', 'conversation_participants',
        'messages', 'message_attachments', 'shops', 'products', 'product_images',
        'product_price_events', 'product_status_events', 'transactions',
        'transaction_status_events', 'payment_attempts', 'delivery_events',
        'refunds', 'disputes', 'report_records', 'reviews', 'simulation_state'
      ]) AS name
     WHERE to_regclass('public.' || name) IS NULL;

    IF missing_tables IS NOT NULL THEN
        RAISE EXCEPTION 'missing required tables: %', missing_tables;
    END IF;

    SELECT array_agg(name ORDER BY name)
      INTO missing_views
      FROM unnest(ARRAY[
        'visible_products', 'visible_account_status_events', 'visible_login_events',
        'visible_account_security_events', 'visible_messages',
        'visible_product_price_events', 'visible_product_status_events',
        'visible_transaction_status_events', 'visible_payment_attempts',
        'visible_delivery_events', 'visible_refunds', 'visible_disputes',
        'visible_report_records'
      ]) AS name
     WHERE to_regclass('public.' || name) IS NULL;

    IF missing_views IS NOT NULL THEN
        RAISE EXCEPTION 'missing required views: %', missing_views;
    END IF;
END $$;

DO $$
DECLARE
    singleton_count BIGINT;
BEGIN
    SELECT count(*) INTO singleton_count FROM simulation_state;
    IF singleton_count <> 1 THEN
        RAISE EXCEPTION 'simulation_state must contain exactly one row, found %', singleton_count;
    END IF;
END $$;

DO $$
BEGIN
    IF (SELECT count(*) FROM accounts) < 120 THEN
        RAISE EXCEPTION 'accounts minimum not met';
    END IF;
    IF (SELECT count(*) FROM devices) < 60 THEN
        RAISE EXCEPTION 'devices minimum not met';
    END IF;
    IF (SELECT count(*) FROM login_events) < 240 THEN
        RAISE EXCEPTION 'login_events minimum not met';
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
    IF (SELECT count(*) FROM payment_attempts) < 100 THEN
        RAISE EXCEPTION 'payment_attempts minimum not met';
    END IF;
    IF (SELECT count(*) FROM delivery_events) < 80 THEN
        RAISE EXCEPTION 'delivery_events minimum not met';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM login_events e
          JOIN accounts a ON a.id = e.account_id
         WHERE e.occurred_at < a.created_at
    ) THEN
        RAISE EXCEPTION 'login event predates its account';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM account_status_events e
          JOIN accounts a ON a.id = e.account_id
         WHERE e.occurred_at < a.created_at
    ) THEN
        RAISE EXCEPTION 'account status event predates its account';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM account_security_events e
          JOIN accounts a ON a.id = e.account_id
         WHERE e.occurred_at < a.created_at
    ) THEN
        RAISE EXCEPTION 'account security event predates its account';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM payment_attempts e
          JOIN transactions t ON t.id = e.transaction_id
         WHERE e.occurred_at < t.created_at
    ) THEN
        RAISE EXCEPTION 'payment attempt predates its transaction';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM delivery_events e
          JOIN transactions t ON t.id = e.transaction_id
         WHERE e.occurred_at < t.created_at
    ) THEN
        RAISE EXCEPTION 'delivery event predates its transaction';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM refunds r
          JOIN transactions t ON t.id = r.transaction_id
         WHERE r.requested_at < t.created_at
            OR (r.completed_at IS NOT NULL AND r.completed_at < r.requested_at)
    ) THEN
        RAISE EXCEPTION 'refund timestamps are inconsistent';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM disputes d
          JOIN transactions t ON t.id = d.transaction_id
         WHERE d.created_at < t.created_at
            OR (d.resolved_at IS NOT NULL AND d.resolved_at < d.created_at)
    ) THEN
        RAISE EXCEPTION 'dispute timestamps are inconsistent';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM messages m
         WHERE NOT EXISTS (
            SELECT 1
              FROM conversation_participants p
             WHERE p.conversation_id = m.conversation_id
               AND p.account_id = m.sender_account_id
         )
    ) THEN
        RAISE EXCEPTION 'message sender is not a conversation participant';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM reviews r
          JOIN transactions t ON t.id = r.transaction_id
         WHERE r.product_id <> t.product_id
            OR r.reviewer_account_id <> t.buyer_account_id
            OR r.created_at < t.created_at
    ) THEN
        RAISE EXCEPTION 'review does not match its transaction';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name IN (
             'accounts', 'account_status_events', 'devices', 'login_events',
             'account_security_events', 'shops', 'products', 'conversations',
             'messages', 'transactions', 'payment_attempts', 'delivery_events',
             'refunds', 'disputes', 'report_records', 'reviews'
           )
           AND column_name IN (
             'is_fraud', 'fraud_type', 'fraud_role', 'expected_detection', 'risk_score'
           )
    ) THEN
        RAISE EXCEPTION 'marketplace tables contain forbidden answer columns';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM visible_account_status_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_login_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_account_security_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_messages v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_product_price_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_product_status_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_transaction_status_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_payment_attempts v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_delivery_events v CROSS JOIN simulation_state s
         WHERE v.occurred_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_refunds v CROSS JOIN simulation_state s
         WHERE v.requested_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_disputes v CROSS JOIN simulation_state s
         WHERE v.created_at > s.simulation_time
    ) OR EXISTS (
        SELECT 1 FROM visible_report_records v CROSS JOIN simulation_state s
         WHERE v.created_at > s.simulation_time
    ) THEN
        RAISE EXCEPTION 'a simulation view exposes future data';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM account_security_events s
          JOIN login_events l ON l.account_id = s.account_id
          JOIN accounts a ON a.id = l.account_id
         WHERE s.event_type IN ('password_reset', 'email_changed')
           AND l.success
           AND l.country_code <> a.country_code
           AND l.occurred_at BETWEEN s.occurred_at AND s.occurred_at + INTERVAL '2 hours'
    ) THEN
        RAISE EXCEPTION 'missing account-takeover-shaped event sequence';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM payment_attempts p1
          JOIN payment_attempts p2
            ON p2.transaction_id = p1.transaction_id
           AND p2.id <> p1.id
         WHERE p1.status IN ('declined', 'failed')
           AND p2.status = 'authorized'
           AND p1.payment_instrument_hash <> p2.payment_instrument_hash
           AND p2.occurred_at > p1.occurred_at
    ) THEN
        RAISE EXCEPTION 'missing payment-instrument-churn sequence';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM refunds r
          JOIN disputes d ON d.transaction_id = r.transaction_id
         WHERE d.created_at >= r.requested_at
    ) THEN
        RAISE EXCEPTION 'missing refund-dispute sequence';
    END IF;
END $$;

SELECT 'environment integrity checks passed' AS result;

ROLLBACK;
