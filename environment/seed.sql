BEGIN;

INSERT INTO simulation_state (
    singleton_id, simulation_time, initial_time, scenario_name, updated_at
) VALUES (
    1,
    TIMESTAMPTZ '2026-09-01 00:00:00+08',
    TIMESTAMPTZ '2026-09-01 00:00:00+08',
    'taiwan-marketplace-20260912',
    TIMESTAMPTZ '2026-09-01 00:00:00+08'
);

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
    CASE WHEN n IN (116, 117) THEN 'restricted' ELSE 'active' END,
    ((n * 17) % 70)::double precision / 100,
    CASE WHEN n % 9 = 0 THEN 'pending' ELSE 'verified' END,
    ((n * 7) % 30)::double precision / 100,
    jsonb_build_object(
        'segment', CASE WHEN n % 5 = 0 THEN 'returning' ELSE 'standard' END,
        'locale', 'zh-TW'
    )
FROM account_rows;

INSERT INTO account_status_events (id, account_id, status, reason, occurred_at)
SELECT
    'ASE-' || lpad(n::text, 4, '0'),
    'ACC-' || lpad(n::text, 4, '0'),
    CASE WHEN n IN (116, 117) THEN 'restricted' ELSE 'active' END,
    CASE WHEN n IN (116, 117) THEN 'manual account review' ELSE 'account created' END,
    TIMESTAMPTZ '2026-06-03 00:00:00+08' + n * INTERVAL '2 hours'
FROM generate_series(1, 120) AS n;

INSERT INTO devices (id, fingerprint_hash, device_type, os_family, created_at)
SELECT
    'DEV-' || lpad(n::text, 4, '0'),
    'sha256-demo-device-' || lpad(n::text, 4, '0'),
    (ARRAY['mobile', 'desktop', 'tablet'])[1 + (n % 3)],
    (ARRAY['iOS', 'Android', 'Windows', 'macOS'])[1 + (n % 4)],
    TIMESTAMPTZ '2026-06-15 00:00:00+08' + n * INTERVAL '1 hour'
FROM generate_series(1, 70) AS n;

INSERT INTO login_events (
    id, account_id, device_id, ip_address, country_code, region_code,
    success, auth_method, occurred_at, attributes
)
SELECT
    'LOG-' || lpad(n::text, 4, '0'),
    'ACC-' || lpad((((n - 1) % 120) + 1)::text, 4, '0'),
    'DEV-' || lpad((((n - 1) % 70) + 1)::text, 4, '0'),
    CASE
        WHEN n % 3 = 0 THEN format('203.0.113.%s', (n % 250) + 1)::inet
        WHEN n % 3 = 1 THEN format('192.0.2.%s', (n % 250) + 1)::inet
        ELSE format('198.51.100.%s', (n % 250) + 1)::inet
    END,
    CASE WHEN n % 12 = 0 THEN 'JP' ELSE 'TW' END,
    CASE WHEN n % 12 = 0 THEN '13' ELSE lpad(((n % 6) + 1)::text, 2, '0') END,
    n % 29 <> 0,
    (ARRAY['password', 'passkey', 'oauth', 'mfa'])[1 + (n % 4)],
    TIMESTAMPTZ '2026-07-01 00:00:00+08' + n * INTERVAL '2 hours',
    CASE WHEN n % 12 = 0
        THEN '{"context":"declared travel"}'::jsonb
        ELSE '{}'::jsonb
    END
FROM generate_series(1, 240) AS n;

INSERT INTO account_security_events (id, account_id, event_type, occurred_at, attributes)
SELECT
    'SEC-' || lpad(n::text, 4, '0'),
    'ACC-' || lpad((((n * 5) - 1) % 120 + 1)::text, 4, '0'),
    (ARRAY['mfa_enabled', 'password_reset', 'phone_changed', 'kyc_changed'])[1 + (n % 4)],
    TIMESTAMPTZ '2026-07-20 08:00:00+08' + n * INTERVAL '6 hours',
    jsonb_build_object('channel', CASE WHEN n % 2 = 0 THEN 'self_service' ELSE 'support' END)
FROM generate_series(1, 24) AS n;

INSERT INTO shops (id, owner_account_id, name, status, created_at, attributes)
SELECT
    'SHOP-' || lpad(n::text, 3, '0'),
    'ACC-' || lpad((n * 4)::text, 4, '0'),
    (ARRAY[
        '海風生活選物', '北城數位小舖', '島嶼日常', '好物研究室', '小山家居', '慢慢衣櫥',
        '晴天戶外', '日光文具', '橘子寵物家', '拾光二手店', '木木廚房', '星河玩具',
        '南方鞋履', '白露美妝', '森野運動', '日日雜貨', '藍窗攝影', '安心手機館'
    ])[n],
    'active',
    TIMESTAMPTZ '2026-07-01 08:00:00+08' + n * INTERVAL '1 hour',
    jsonb_build_object('fulfillment', CASE WHEN n % 3 = 0 THEN 'merchant' ELSE 'platform' END)
FROM generate_series(1, 18) AS n;

WITH product_rows AS (
    SELECT
        n,
        ((n - 1) % 18) + 1 AS shop_n,
        (ARRAY[
            '無線藍牙耳機', '純棉休閒上衣', '不鏽鋼保溫杯', '折疊收納箱', '行動電源',
            '機械鍵盤', '防水登山背包', '寵物飲水器', '手沖咖啡壺', '二手拍立得'
        ])[1 + ((n - 1) % 10)] AS title,
        (ARRAY['3C', '服飾', '居家', '戶外', '寵物', '生活'])[1 + ((n - 1) % 6)] AS category,
        (199 + ((n * 37) % 4000))::numeric(14,2) AS price,
        TIMESTAMPTZ '2026-07-05 08:00:00+08' + n * INTERVAL '1 hour' AS created_at
    FROM generate_series(1, 90) AS n
)
INSERT INTO products (
    id, shop_id, seller_account_id, title, description, category,
    image_urls, price, currency, created_at, attributes
)
SELECT
    'PROD-' || lpad(n::text, 4, '0'),
    'SHOP-' || lpad(shop_n::text, 3, '0'),
    'ACC-' || lpad((shop_n * 4)::text, 4, '0'),
    title,
    '虛構測試商品，僅供本地資料環境使用。',
    category,
    jsonb_build_array('https://images.marketplace.test/products/' || lpad(n::text, 4, '0') || '.jpg'),
    price,
    'TWD',
    created_at,
    jsonb_build_object('condition', CASE WHEN n % 10 = 0 THEN 'used' ELSE 'new' END)
FROM product_rows;

INSERT INTO product_images (id, product_id, image_url, image_hash, created_at)
SELECT
    'IMG-' || lpad(n::text, 4, '0'),
    'PROD-' || lpad(n::text, 4, '0'),
    'https://images.marketplace.test/products/' || lpad(n::text, 4, '0') || '.jpg',
    'sha256-demo-image-' || lpad(n::text, 4, '0'),
    TIMESTAMPTZ '2026-07-05 10:00:00+08' + n * INTERVAL '1 hour'
FROM generate_series(1, 90) AS n;

INSERT INTO product_price_events (id, product_id, price, currency, occurred_at)
SELECT
    'PPE-' || lpad(n::text, 4, '0'),
    id,
    price,
    currency,
    created_at + INTERVAL '1 hour'
FROM products
CROSS JOIN LATERAL (
    SELECT substring(products.id FROM '[0-9]+$')::integer AS n
) AS parsed;

INSERT INTO product_status_events (id, product_id, status, reason, occurred_at)
SELECT
    'PSE-' || lpad(n::text, 4, '0'),
    id,
    'active',
    'listing published',
    created_at + INTERVAL '2 hours'
FROM products
CROSS JOIN LATERAL (
    SELECT substring(products.id FROM '[0-9]+$')::integer AS n
) AS parsed;

WITH transaction_rows AS (
    SELECT
        n,
        ((n - 1) % 90) + 1 AS product_n,
        ((n - 1) % 40) + 81 AS buyer_n,
        (n % 3) + 1 AS quantity,
        TIMESTAMPTZ '2026-08-01 08:00:00+08' + n * INTERVAL '2 hours' AS created_at
    FROM generate_series(1, 100) AS n
)
INSERT INTO transactions (
    id, buyer_account_id, seller_account_id, product_id, payment_method,
    quantity, amount, currency, status, created_at, attributes
)
SELECT
    'TXN-' || lpad(r.n::text, 4, '0'),
    'ACC-' || lpad(r.buyer_n::text, 4, '0'),
    p.seller_account_id,
    p.id,
    (ARRAY['credit_card', 'wallet', 'bank_transfer'])[1 + (r.n % 3)],
    r.quantity,
    p.price * r.quantity,
    'TWD',
    CASE
        WHEN r.n % 17 = 0 THEN 'cancelled'
        WHEN r.n % 20 = 0 THEN 'refunded'
        ELSE 'delivered'
    END,
    r.created_at,
    CASE WHEN r.n BETWEEN 41 AND 60
        THEN '{"campaign":"autumn_flash_sale"}'::jsonb
        ELSE '{}'::jsonb
    END
FROM transaction_rows r
JOIN products p ON p.id = 'PROD-' || lpad(r.product_n::text, 4, '0');

INSERT INTO transaction_status_events (id, transaction_id, status, occurred_at)
SELECT 'TSE-C-' || lpad(n::text, 4, '0'), id, 'created', created_at
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed;

INSERT INTO transaction_status_events (id, transaction_id, status, occurred_at)
SELECT 'TSE-P-' || lpad(n::text, 4, '0'), id, 'paid', created_at + INTERVAL '15 minutes'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status <> 'cancelled';

INSERT INTO transaction_status_events (id, transaction_id, status, occurred_at)
SELECT 'TSE-S-' || lpad(n::text, 4, '0'), id, 'shipped', created_at + INTERVAL '1 day'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status <> 'cancelled';

INSERT INTO transaction_status_events (id, transaction_id, status, occurred_at)
SELECT 'TSE-D-' || lpad(n::text, 4, '0'), id, 'delivered', created_at + INTERVAL '3 days'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status <> 'cancelled';

INSERT INTO transaction_status_events (id, transaction_id, status, occurred_at)
SELECT
    CASE WHEN status = 'cancelled' THEN 'TSE-X-' ELSE 'TSE-R-' END || lpad(n::text, 4, '0'),
    id,
    CASE WHEN status = 'cancelled' THEN 'cancelled' ELSE 'refunded' END,
    created_at + CASE WHEN status = 'cancelled' THEN INTERVAL '20 minutes' ELSE INTERVAL '5 days' END
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status IN ('cancelled', 'refunded');

INSERT INTO payment_attempts (
    id, transaction_id, payer_account_id, payment_method, payment_instrument_hash,
    amount, currency, status, failure_code, device_id, ip_address, occurred_at
)
SELECT
    'PAY-' || lpad(n::text, 4, '0'),
    t.id,
    t.buyer_account_id,
    t.payment_method,
    'sha256-demo-payment-' || lpad((((n - 1) % 45) + 1)::text, 4, '0'),
    t.amount,
    t.currency,
    CASE WHEN t.status = 'cancelled' THEN 'declined' ELSE 'authorized' END,
    CASE WHEN t.status = 'cancelled' THEN 'ISSUER_DECLINED' END,
    'DEV-' || lpad((((n - 1) % 70) + 1)::text, 4, '0'),
    format('198.51.100.%s', (n % 250) + 1)::inet,
    t.created_at + INTERVAL '10 minutes'
FROM transactions t
CROSS JOIN LATERAL (
    SELECT substring(t.id FROM '[0-9]+$')::integer AS n
) AS parsed;

INSERT INTO delivery_events (id, transaction_id, status, occurred_at, attributes)
SELECT 'DEL-P-' || lpad(n::text, 4, '0'), id, 'picked_up', created_at + INTERVAL '1 day', '{}'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status <> 'cancelled';

INSERT INTO delivery_events (id, transaction_id, status, occurred_at, attributes)
SELECT
    'DEL-D-' || lpad(n::text, 4, '0'),
    id,
    'delivered',
    created_at + INTERVAL '3 days',
    CASE WHEN n % 11 = 0 THEN '{"delivery_note":"recipient confirmed"}'::jsonb ELSE '{}'::jsonb END
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status <> 'cancelled';

INSERT INTO refunds (
    id, transaction_id, requester_account_id, reason, amount,
    status, requested_at, completed_at
)
SELECT
    'REF-' || lpad(n::text, 4, '0'),
    id,
    buyer_account_id,
    '商品尺寸不合，依平台流程退貨',
    amount,
    'completed',
    created_at + INTERVAL '4 days',
    created_at + INTERVAL '5 days'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE n % 20 = 0;

INSERT INTO disputes (
    id, transaction_id, opened_by_account_id, reason, status, created_at, resolved_at
)
SELECT
    'DSP-' || lpad(n::text, 4, '0'),
    id,
    buyer_account_id,
    '收到商品與頁面描述有差異',
    'resolved_buyer',
    created_at + INTERVAL '6 days',
    created_at + INTERVAL '8 days'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE n % 25 = 0;

INSERT INTO conversations (id, shop_id, transaction_id, created_at)
SELECT
    'CONV-' || lpad(n::text, 3, '0'),
    p.shop_id,
    t.id,
    t.created_at + INTERVAL '30 minutes'
FROM generate_series(1, 40) AS n
JOIN transactions t ON t.id = 'TXN-' || lpad(n::text, 4, '0')
JOIN products p ON p.id = t.product_id;

INSERT INTO conversation_participants (conversation_id, account_id, participant_role, joined_at)
SELECT c.id, t.buyer_account_id, 'buyer', c.created_at
FROM conversations c
JOIN transactions t ON t.id = c.transaction_id
UNION ALL
SELECT c.id, t.seller_account_id, 'seller', c.created_at
FROM conversations c
JOIN transactions t ON t.id = c.transaction_id;

WITH message_rows AS (
    SELECT
        n,
        ((n - 1) % 40) + 1 AS conversation_n,
        TIMESTAMPTZ '2026-08-10 09:00:00+08' + n * INTERVAL '20 minutes' AS created_at,
        (ARRAY[
            '您好，請問今天下單大約何時出貨？',
            '庫存充足，付款完成後會依序包裝。',
            '尺寸表我看過了，麻煩幫我保留藍色。',
            '沒問題，平台訂單成立後會為您保留。',
            '物流進度可以在訂單頁面直接查詢。',
            '收到商品了，包裝完整，謝謝。',
            '銀行轉帳也請使用平台內建付款，不需要私下匯款。',
            '官方退貨步驟在 https://help.marketplace.test/returns 。',
            '這筆刷卡第一次失敗，我會在平台內重新付款。',
            '旅途中登入通知是我本人操作，裝置沒有更換。'
        ])[1 + ((n - 1) % 10)] AS body
    FROM generate_series(1, 420) AS n
)
INSERT INTO messages (
    id, conversation_id, sender_account_id, recipient_account_id,
    message_type, text, image_urls, urls, created_at, attributes
)
SELECT
    'MSG-' || lpad(r.n::text, 4, '0'),
    c.id,
    CASE WHEN r.n % 2 = 1 THEN t.buyer_account_id ELSE t.seller_account_id END,
    CASE WHEN r.n % 2 = 1 THEN t.seller_account_id ELSE t.buyer_account_id END,
    'text',
    r.body,
    '[]'::jsonb,
    CASE WHEN r.n % 10 = 8
        THEN '["https://help.marketplace.test/returns"]'::jsonb
        ELSE '[]'::jsonb
    END,
    r.created_at,
    CASE
        WHEN r.n % 10 IN (7, 8, 9, 0) THEN '{"context":"legitimate_edge_case"}'::jsonb
        ELSE '{}'::jsonb
    END
FROM message_rows r
JOIN conversations c ON c.id = 'CONV-' || lpad(r.conversation_n::text, 3, '0')
JOIN transactions t ON t.id = c.transaction_id;

INSERT INTO message_attachments (id, message_id, attachment_type, resource_url, mime_type, created_at)
SELECT
    'ATT-' || lpad(n::text, 4, '0'),
    id,
    'image',
    'https://images.marketplace.test/chat/' || lpad(n::text, 4, '0') || '.jpg',
    'image/jpeg',
    created_at
FROM messages
CROSS JOIN LATERAL (
    SELECT substring(messages.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE n BETWEEN 1 AND 420 AND n % 21 = 0;

INSERT INTO reviews (id, product_id, transaction_id, reviewer_account_id, rating, text, created_at)
SELECT
    'REV-' || lpad(n::text, 4, '0'),
    product_id,
    id,
    buyer_account_id,
    ((n % 5) + 1)::smallint,
    (ARRAY[
        '商品符合描述。', '包裝仔細，出貨速度正常。', '尺寸合適。',
        '客服回覆清楚。', '整體交易順利。'
    ])[1 + (n % 5)],
    created_at + INTERVAL '4 days'
FROM transactions
CROSS JOIN LATERAL (
    SELECT substring(transactions.id FROM '[0-9]+$')::integer AS n
) AS parsed
WHERE status = 'delivered';

INSERT INTO report_records (
    id, reporter_account_id, target_account_id, target_type, target_id,
    type, reason, status, created_at, attributes
)
SELECT
    'RPT-' || lpad(n::text, 4, '0'),
    t.buyer_account_id,
    t.seller_account_id,
    'account',
    t.seller_account_id,
    'report',
    CASE WHEN n % 2 = 0 THEN '商品資訊需要確認' ELSE '回覆速度過慢' END,
    CASE WHEN n % 3 = 0 THEN 'resolved' ELSE 'reviewing' END,
    t.created_at + INTERVAL '5 days',
    '{}'::jsonb
FROM generate_series(1, 20) AS n
JOIN transactions t ON t.id = 'TXN-' || lpad(n::text, 4, '0');

-- Future account-access sequences: visible only after simulation time advances.
INSERT INTO account_security_events (id, account_id, event_type, occurred_at, attributes)
VALUES
    ('SEC-0901', 'ACC-0101', 'password_reset', TIMESTAMPTZ '2026-09-02 09:00:00+08', '{"channel":"email"}'),
    ('SEC-0902', 'ACC-0102', 'email_changed', TIMESTAMPTZ '2026-09-03 14:00:00+08', '{"channel":"self_service"}');

INSERT INTO login_events (
    id, account_id, device_id, ip_address, country_code, region_code,
    success, auth_method, occurred_at, attributes
)
VALUES
    ('LOG-0901', 'ACC-0101', 'DEV-0069', '203.0.113.241', 'SG', '01', TRUE, 'password', TIMESTAMPTZ '2026-09-02 09:25:00+08', '{"device_novel":true}'),
    ('LOG-0902', 'ACC-0102', 'DEV-0070', '203.0.113.242', 'JP', '13', TRUE, 'oauth', TIMESTAMPTZ '2026-09-03 14:40:00+08', '{"device_novel":true}');

-- Future payment-instrument churn on otherwise existing transactions.
INSERT INTO payment_attempts (
    id, transaction_id, payer_account_id, payment_method, payment_instrument_hash,
    amount, currency, status, failure_code, device_id, ip_address, occurred_at
)
VALUES
    ('PAY-0901', 'TXN-0091', 'ACC-0091', 'credit_card', 'sha256-demo-payment-x901', 0, 'TWD', 'failed', 'INSTRUMENT_MISMATCH', 'DEV-0069', '203.0.113.241', TIMESTAMPTZ '2026-09-04 10:00:00+08'),
    ('PAY-0902', 'TXN-0091', 'ACC-0091', 'credit_card', 'sha256-demo-payment-x902', 0, 'TWD', 'authorized', NULL, 'DEV-0069', '203.0.113.241', TIMESTAMPTZ '2026-09-04 10:08:00+08'),
    ('PAY-0903', 'TXN-0092', 'ACC-0092', 'wallet', 'sha256-demo-payment-x903', 0, 'TWD', 'declined', 'VELOCITY_LIMIT', 'DEV-0070', '203.0.113.242', TIMESTAMPTZ '2026-09-05 11:00:00+08'),
    ('PAY-0904', 'TXN-0092', 'ACC-0092', 'wallet', 'sha256-demo-payment-x904', 0, 'TWD', 'authorized', NULL, 'DEV-0070', '203.0.113.242', TIMESTAMPTZ '2026-09-05 11:06:00+08');

UPDATE payment_attempts p
   SET amount = t.amount
  FROM transactions t
 WHERE p.transaction_id = t.id
   AND p.id LIKE 'PAY-09%';

-- Fictional ecommerce conversations adapted from aggregate Cofacts scam themes.
WITH injected (
    id, conversation_id, sender_role, body, event_time, destination
) AS (
    VALUES
    ('MSG-0901', 'CONV-031', 'seller', '系統顯示收款設定未完成，請到驗證頁重新開通，完成後我才能出貨。', TIMESTAMPTZ '2026-09-02 10:00:00+08', 'https://verify-market.invalid/session'),
    ('MSG-0902', 'CONV-031', 'buyer',  '為什麼不能直接在平台訂單頁完成？', TIMESTAMPTZ '2026-09-02 10:05:00+08', NULL),
    ('MSG-0903', 'CONV-032', 'seller', '物流客服說包裹資料異常，請用這個頁面補填付款資料。', TIMESTAMPTZ '2026-09-02 15:00:00+08', 'https://parcel-check.invalid/update'),
    ('MSG-0904', 'CONV-032', 'buyer',  '我會先從平台聯絡官方客服確認。', TIMESTAMPTZ '2026-09-02 15:04:00+08', NULL),
    ('MSG-0905', 'CONV-033', 'buyer',  '我下單後收到通知說要解除重複扣款，可以協助嗎？', TIMESTAMPTZ '2026-09-03 09:00:00+08', NULL),
    ('MSG-0906', 'CONV-033', 'seller', '請不要提供卡片資料，平台不會要求私下操作提款機。', TIMESTAMPTZ '2026-09-03 09:03:00+08', NULL),
    ('MSG-0907', 'CONV-034', 'seller', '限時價格只保留十分鐘，請離開賣場改用外部轉帳。', TIMESTAMPTZ '2026-09-03 20:00:00+08', NULL),
    ('MSG-0908', 'CONV-034', 'buyer',  '我只會使用平台付款，不會私下匯款。', TIMESTAMPTZ '2026-09-03 20:02:00+08', NULL),
    ('MSG-0909', 'CONV-035', 'seller', '帳號被限制收款，麻煩先加客服完成買家認證。', TIMESTAMPTZ '2026-09-04 08:00:00+08', 'https://support-center.invalid/contact'),
    ('MSG-0910', 'CONV-035', 'buyer',  '請提供平台內的案件編號，我不開外部連結。', TIMESTAMPTZ '2026-09-04 08:06:00+08', NULL),
    ('MSG-0911', 'CONV-036', 'seller', '這是最後一件二手相機，先匯保留金就不會被別人買走。', TIMESTAMPTZ '2026-09-05 12:00:00+08', NULL),
    ('MSG-0912', 'CONV-036', 'buyer',  '請直接建立平台訂單，我不支付站外保留金。', TIMESTAMPTZ '2026-09-05 12:03:00+08', NULL),
    ('MSG-0913', 'CONV-037', 'buyer',  '包裹裡只有填充物，商品不在裡面。', TIMESTAMPTZ '2026-09-06 18:00:00+08', NULL),
    ('MSG-0914', 'CONV-037', 'seller', '物流顯示已簽收，我這邊無法處理。', TIMESTAMPTZ '2026-09-06 18:10:00+08', NULL),
    ('MSG-0915', 'CONV-038', 'buyer',  '商品圖片和另一個賣場完全相同，請提供實拍。', TIMESTAMPTZ '2026-09-07 11:00:00+08', NULL),
    ('MSG-0916', 'CONV-038', 'seller', '照片就是實品，今天付款可以再便宜一半。', TIMESTAMPTZ '2026-09-07 11:02:00+08', NULL),
    ('MSG-0917', 'CONV-039', 'buyer',  '我沒有收到商品，請立刻退款，不然會向銀行提出爭議。', TIMESTAMPTZ '2026-09-08 10:00:00+08', NULL),
    ('MSG-0918', 'CONV-039', 'seller', '物流有簽收照片，我已請平台調查。', TIMESTAMPTZ '2026-09-08 10:04:00+08', NULL),
    ('MSG-0919', 'CONV-040', 'buyer',  '我已經申請退款，也會另外提出未授權交易申訴。', TIMESTAMPTZ '2026-09-09 16:00:00+08', NULL),
    ('MSG-0920', 'CONV-040', 'seller', '請在同一案件補充證據，避免重複申請。', TIMESTAMPTZ '2026-09-09 16:06:00+08', NULL)
)
INSERT INTO messages (
    id, conversation_id, sender_account_id, recipient_account_id,
    message_type, text, image_urls, urls, created_at, attributes
)
SELECT
    i.id,
    c.id,
    CASE WHEN i.sender_role = 'buyer' THEN t.buyer_account_id ELSE t.seller_account_id END,
    CASE WHEN i.sender_role = 'buyer' THEN t.seller_account_id ELSE t.buyer_account_id END,
    'text',
    i.body,
    '[]'::jsonb,
    CASE WHEN i.destination IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(i.destination) END,
    i.event_time,
    '{}'::jsonb
FROM injected i
JOIN conversations c ON c.id = i.conversation_id
JOIN transactions t ON t.id = c.transaction_id;

INSERT INTO message_attachments (id, message_id, attachment_type, resource_url, mime_type, created_at)
SELECT
    'ATT-' || substring(m.id FROM '[0-9]+$'),
    m.id,
    'url',
    url_value,
    'text/html',
    m.created_at
FROM messages m
CROSS JOIN LATERAL jsonb_array_elements_text(m.urls) AS url_value
WHERE m.id LIKE 'MSG-09%';

-- Seller-side listing signals: reused image and abrupt pricing/status changes.
INSERT INTO product_images (id, product_id, image_url, image_hash, created_at)
VALUES
    ('IMG-0901', 'PROD-0081', 'https://images.marketplace.test/derived/0901.jpg', 'sha256-demo-reused-listing', TIMESTAMPTZ '2026-09-04 09:00:00+08'),
    ('IMG-0902', 'PROD-0082', 'https://images.marketplace.test/derived/0902.jpg', 'sha256-demo-reused-listing', TIMESTAMPTZ '2026-09-04 09:05:00+08');

INSERT INTO product_price_events (id, product_id, price, currency, occurred_at)
VALUES
    ('PPE-0901', 'PROD-0081', 99.00, 'TWD', TIMESTAMPTZ '2026-09-04 09:10:00+08'),
    ('PPE-0902', 'PROD-0082', 109.00, 'TWD', TIMESTAMPTZ '2026-09-04 09:12:00+08');

INSERT INTO product_status_events (id, product_id, status, reason, occurred_at)
VALUES
    ('PSE-0901', 'PROD-0081', 'removed', 'listing under review', TIMESTAMPTZ '2026-09-10 09:00:00+08'),
    ('PSE-0902', 'PROD-0082', 'removed', 'listing under review', TIMESTAMPTZ '2026-09-10 09:05:00+08');

-- Buyer-side repeated refund and dispute sequences.
INSERT INTO refunds (
    id, transaction_id, requester_account_id, reason, amount,
    status, requested_at, completed_at
)
SELECT
    v.refund_id,
    t.id,
    t.buyer_account_id,
    v.reason,
    t.amount,
    'requested',
    v.requested_at,
    NULL
FROM (VALUES
    ('REF-0901', 'TXN-0093', '包裹內容與訂單不符', TIMESTAMPTZ '2026-09-08 09:00:00+08'),
    ('REF-0902', 'TXN-0094', '聲稱未收到已簽收商品', TIMESTAMPTZ '2026-09-09 09:00:00+08')
) AS v(refund_id, transaction_id, reason, requested_at)
JOIN transactions t ON t.id = v.transaction_id;

INSERT INTO disputes (
    id, transaction_id, opened_by_account_id, reason, status, created_at, resolved_at
)
SELECT
    v.dispute_id,
    t.id,
    t.buyer_account_id,
    v.reason,
    'open',
    v.created_at,
    NULL
FROM (VALUES
    ('DSP-0901', 'TXN-0093', '退款處理中另向支付機構爭議', TIMESTAMPTZ '2026-09-08 10:00:00+08'),
    ('DSP-0902', 'TXN-0094', '退款申請後重複提出未授權交易', TIMESTAMPTZ '2026-09-09 10:00:00+08')
) AS v(dispute_id, transaction_id, reason, created_at)
JOIN transactions t ON t.id = v.transaction_id;

INSERT INTO report_records (
    id, reporter_account_id, target_account_id, target_type, target_id,
    type, reason, status, created_at, attributes
)
SELECT
    v.report_id,
    t.buyer_account_id,
    t.seller_account_id,
    'transaction',
    t.id,
    'report',
    v.reason,
    'open',
    v.created_at,
    '{}'::jsonb
FROM (VALUES
    ('RPT-0901', 'TXN-0031', '對方要求離開平台驗證付款', TIMESTAMPTZ '2026-09-02 11:00:00+08'),
    ('RPT-0902', 'TXN-0032', '外部物流頁要求補填付款資料', TIMESTAMPTZ '2026-09-02 16:00:00+08'),
    ('RPT-0903', 'TXN-0037', '收到空包裹', TIMESTAMPTZ '2026-09-06 19:00:00+08'),
    ('RPT-0904', 'TXN-0038', '商品圖片疑似重複使用', TIMESTAMPTZ '2026-09-07 12:00:00+08')
) AS v(report_id, transaction_id, reason, created_at)
JOIN transactions t ON t.id = v.transaction_id;

-- Small compatibility graph for the existing read-only system tools.
INSERT INTO entities (id, type, label, attributes)
SELECT id, 'account', NULL, '{}'::jsonb
FROM accounts
WHERE id BETWEEN 'ACC-0001' AND 'ACC-0010';

INSERT INTO entities (id, type, label, attributes)
VALUES
    ('IP-203-0-113-241', 'ip', '203.0.113.241', '{}'),
    ('DEVICE-0069', 'device', 'DEV-0069', '{}');

INSERT INTO relationships (
    source_id, target_id, type, value, confidence,
    evidence_refs, first_seen_at, last_seen_at
)
VALUES
    ('ACC-0001', 'IP-203-0-113-241', 'login_from', '203.0.113.241', 1, '["LOG-0001"]', TIMESTAMPTZ '2026-07-01 02:00:00+08', TIMESTAMPTZ '2026-07-01 02:00:00+08'),
    ('ACC-0001', 'DEVICE-0069', 'uses_device', 'DEV-0069', 1, '["LOG-0001"]', TIMESTAMPTZ '2026-07-01 02:00:00+08', TIMESTAMPTZ '2026-07-01 02:00:00+08');

INSERT INTO cases (
    id, source, subject_type, subject_id, status, risk_score,
    trigger_reason, created_at, updated_at, attributes
)
VALUES
    ('CASE-DEMO-001', 'manual', 'account', 'ACC-0001', 'closed', 0.12,
     'Historical compatibility example unrelated to injected journeys',
     TIMESTAMPTZ '2026-07-15 09:00:00+08', TIMESTAMPTZ '2026-07-16 09:00:00+08', '{}');

INSERT INTO case_entities (case_id, entity_id, role)
VALUES ('CASE-DEMO-001', 'ACC-0001', 'subject');

COMMIT;
