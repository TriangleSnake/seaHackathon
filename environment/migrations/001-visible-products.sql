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
