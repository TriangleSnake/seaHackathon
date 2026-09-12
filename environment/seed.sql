INSERT INTO accounts (id, created_at, status, activity_score, kyc_status, bot_check_score)
VALUES
    ('acct-known-fraud', NOW() - INTERVAL '90 days', 'banned', 0.95, 'rejected', 0.92),
    ('acct-suspicious-1', NOW() - INTERVAL '2 days', 'active', 0.88, 'unverified', 0.81),
    ('acct-suspicious-2', NOW() - INTERVAL '1 day', 'active', 0.76, 'unverified', 0.73),
    ('acct-normal', NOW() - INTERVAL '2 years', 'active', 0.20, 'verified', 0.05)
ON CONFLICT (id) DO NOTHING;

INSERT INTO login_events (id, account_id, ip_address, device_id, occurred_at)
VALUES
    ('login-001', 'acct-known-fraud', '203.0.113.42', 'device-shared-001', NOW() - INTERVAL '3 days'),
    ('login-002', 'acct-suspicious-1', '203.0.113.42', 'device-shared-001', NOW() - INTERVAL '2 days'),
    ('login-003', 'acct-suspicious-2', '203.0.113.42', 'device-shared-001', NOW() - INTERVAL '1 day'),
    ('login-004', 'acct-normal', '198.51.100.10', 'device-normal-001', NOW() - INTERVAL '1 day')
ON CONFLICT (id) DO NOTHING;

INSERT INTO cases (id, source, subject_type, subject_id, status, risk_score, trigger_reason)
VALUES ('case-001', 'detection', 'account', 'acct-known-fraud', 'confirmed_fraud', 0.98, 'Known fraud seed')
ON CONFLICT (id) DO NOTHING;

INSERT INTO entities (id, type, label)
VALUES
    ('acct-known-fraud', 'account', 'Known fraud account'),
    ('acct-suspicious-1', 'account', 'Suspicious account 1'),
    ('acct-suspicious-2', 'account', 'Suspicious account 2'),
    ('ip:203.0.113.42', 'ip', '203.0.113.42'),
    ('device:device-shared-001', 'device', 'device-shared-001')
ON CONFLICT (id) DO NOTHING;

INSERT INTO relationships (source_id, target_id, type, value, confidence, evidence_refs, first_seen_at, last_seen_at)
VALUES
    ('acct-known-fraud', 'ip:203.0.113.42', 'login_from', '203.0.113.42', 1, '["login-001"]', NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days'),
    ('acct-suspicious-1', 'ip:203.0.113.42', 'login_from', '203.0.113.42', 1, '["login-002"]', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'),
    ('acct-suspicious-2', 'ip:203.0.113.42', 'login_from', '203.0.113.42', 1, '["login-003"]', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day'),
    ('acct-known-fraud', 'device:device-shared-001', 'uses_device', 'device-shared-001', 1, '["login-001"]', NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days'),
    ('acct-suspicious-1', 'device:device-shared-001', 'uses_device', 'device-shared-001', 1, '["login-002"]', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'),
    ('acct-suspicious-2', 'device:device-shared-001', 'uses_device', 'device-shared-001', 1, '["login-003"]', NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day')
ON CONFLICT (source_id, target_id, type) DO NOTHING;
