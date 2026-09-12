\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM payment_attempts p JOIN delivery_events d ON d.transaction_id=p.transaction_id AND d.status='delivered' WHERE p.occurred_at>d.occurred_at) THEN
        RAISE EXCEPTION 'seed payment occurs after delivery';
    END IF;
    IF EXISTS (SELECT 1 FROM relationships r JOIN login_events l ON l.id=r.evidence_refs->>0 WHERE r.source_id<>l.account_id OR (r.type='login_from' AND r.value<>host(l.ip_address)) OR (r.type='uses_device' AND r.value<>l.device_id)) THEN
        RAISE EXCEPTION 'graph contradicts cited login';
    END IF;
    IF EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.created_at<c.created_at) THEN
        RAISE EXCEPTION 'message precedes conversation';
    END IF;
    IF EXISTS (SELECT 1 FROM messages m WHERE m.recipient_account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM conversation_participants p WHERE p.account_id=m.recipient_account_id AND p.conversation_id=m.conversation_id AND p.joined_at<=m.created_at)) THEN
        RAISE EXCEPTION 'recipient not yet a participant';
    END IF;
    IF EXISTS (SELECT conversation_id FROM messages WHERE id BETWEEN 'MSG-0001' AND 'MSG-0420' GROUP BY conversation_id HAVING count(DISTINCT sender_account_id)<2 OR count(DISTINCT text)<5) THEN
        RAISE EXCEPTION 'normal conversation lacks dialogue variety';
    END IF;
    IF (SELECT count(*) FROM messages WHERE id BETWEEN 'MSG-0001' AND 'MSG-0420' AND created_at >= TIMESTAMPTZ '2026-09-01 00:00+08')<>420 THEN
        RAISE EXCEPTION 'normal messages do not overlap evaluation period';
    END IF;
    IF EXISTS(SELECT 1 FROM login_events l WHERE NOT(attributes ? 'device_novel') OR (attributes->>'device_novel')::boolean IS DISTINCT FROM
        (l.success AND l.device_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM login_events p WHERE p.account_id=l.account_id AND p.device_id=l.device_id AND p.success AND (p.occurred_at,p.id)<(l.occurred_at,l.id)))) THEN
        RAISE EXCEPTION 'inconsistent first-successful-device observation';
    END IF;
    IF (SELECT transaction_id FROM conversations WHERE id='CONV-037') <> (SELECT transaction_id FROM refunds WHERE id='REF-0901') OR
       (SELECT transaction_id FROM conversations WHERE id='CONV-039') <> (SELECT transaction_id FROM disputes WHERE id='DSP-0902') THEN
        RAISE EXCEPTION 'claims conversation and structured events refer to different transactions';
    END IF;
END $$;
SELECT set_simulation_time(TIMESTAMPTZ '2026-09-04 09:09:59+08');
DO $$ BEGIN
    IF (SELECT price FROM visible_products WHERE id='PROD-0081')<>3196 THEN RAISE EXCEPTION 'future price leaked'; END IF;
    IF EXISTS(SELECT 1 FROM visible_products WHERE created_at>(SELECT simulation_time FROM simulation_state)) THEN RAISE EXCEPTION 'future product leaked'; END IF;
END $$;
SELECT set_simulation_time(TIMESTAMPTZ '2026-09-04 09:10:00+08');
DO $$ BEGIN
    IF (SELECT price FROM visible_products WHERE id='PROD-0081')<>99 THEN RAISE EXCEPTION 'price event not applied'; END IF;
    IF (SELECT price FROM products WHERE id='PROD-0081')<>3196 THEN RAISE EXCEPTION 'base price must retain history'; END IF;
END $$;
SELECT 'environment quality checks passed';
ROLLBACK;
