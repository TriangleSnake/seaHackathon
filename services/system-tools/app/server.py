from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .db import fetch_all, fetch_one


mcp = FastMCP(
    "fraud-intelligence-system-tools",
    instructions=(
        "Use these read-only domain tools to inspect fraud intelligence data. "
        "Every conclusion must cite record IDs returned by the tools."
    ),
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def bounded_limit(limit: int) -> int:
    return max(1, min(limit, 100))


@mcp.tool()
async def database_health() -> dict[str, Any]:
    """Check whether the system PostgreSQL database is reachable."""
    row = await fetch_one("SELECT current_database() AS database, NOW() AS checked_at")
    return {"ok": row is not None, **(row or {})}


@mcp.tool()
async def get_patrol_overview(lookback_hours: int = 24) -> dict[str, Any]:
    """Summarize recent system activity so Patrol can choose an exploration direction."""
    hours = max(1, min(lookback_hours, 24 * 30))
    row = await fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM accounts
           WHERE created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS new_account_count,
          (SELECT COUNT(*) FROM visible_login_events
           WHERE occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS login_count,
          (SELECT COUNT(DISTINCT ip_address) FROM visible_login_events
           WHERE occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS distinct_ip_count,
          (SELECT COUNT(*) FROM products
           WHERE created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS product_count,
          (SELECT COUNT(*) FROM visible_messages
           WHERE created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS message_count,
          (SELECT COUNT(*) FROM visible_report_records
           WHERE created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')) AS report_count,
          (SELECT COUNT(*) FROM cases
           WHERE status IN ('pending', 'investigating', 'manual_review')) AS open_case_count
        """,
        (hours, hours, hours, hours, hours, hours),
    )
    return {
        "lookback_hours": hours,
        "observed_at": datetime.now().astimezone().isoformat(),
        **(row or {}),
    }


@mcp.tool()
async def find_high_density_ips(
    lookback_hours: int = 72,
    minimum_accounts: int = 3,
    limit: int = 20,
) -> dict[str, Any]:
    """Find IPs used by many accounts recently, with login IDs usable as evidence."""
    hours = max(1, min(lookback_hours, 24 * 30))
    minimum = max(2, min(minimum_accounts, 100))
    rows = await fetch_all(
        """
        SELECT ip_address::text AS ip_address,
               COUNT(DISTINCT account_id) AS account_count,
               ARRAY_AGG(DISTINCT account_id ORDER BY account_id) AS account_ids,
               ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs,
               MIN(occurred_at) AS first_seen_at,
               MAX(occurred_at) AS last_seen_at
        FROM visible_login_events
        WHERE occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')
        GROUP BY ip_address
        HAVING COUNT(DISTINCT account_id) >= %s
        ORDER BY account_count DESC, last_seen_at DESC
        LIMIT %s
        """,
        (hours, minimum, bounded_limit(limit)),
    )
    return {
        "lookback_hours": hours,
        "minimum_accounts": minimum,
        "clusters": rows,
        "count": len(rows),
    }


@mcp.tool()
async def find_new_account_bursts(
    account_age_days: int = 14,
    lookback_hours: int = 24,
    minimum_events: int = 5,
    limit: int = 20,
) -> dict[str, Any]:
    """Find young accounts with bursty login, listing, or message activity and evidence IDs."""
    age_days = max(1, min(account_age_days, 90))
    hours = max(1, min(lookback_hours, 24 * 30))
    minimum = max(1, min(minimum_events, 10000))
    rows = await fetch_all(
        """
        WITH recent_activity AS (
          SELECT a.id AS account_id, a.created_at, a.status, a.activity_score,
                 COUNT(DISTINCT l.id) AS login_count,
                 COUNT(DISTINCT p.id) AS product_count,
                 COUNT(DISTINCT m.id) AS message_count,
                 ARRAY_REMOVE(ARRAY_AGG(DISTINCT l.id), NULL) ||
                 ARRAY_REMOVE(ARRAY_AGG(DISTINCT p.id), NULL) ||
                 ARRAY_REMOVE(ARRAY_AGG(DISTINCT m.id), NULL) AS evidence_refs
          FROM accounts a
          LEFT JOIN visible_login_events l ON l.account_id = a.id
            AND l.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')
          LEFT JOIN products p ON p.seller_account_id = a.id
            AND p.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')
          LEFT JOIN visible_messages m ON m.sender_account_id = a.id
            AND m.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 hour')
          WHERE a.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
          GROUP BY a.id
        )
        SELECT *, (login_count + product_count + message_count) AS total_event_count
        FROM recent_activity
        WHERE (login_count + product_count + message_count) >= %s
        ORDER BY total_event_count DESC, created_at DESC
        LIMIT %s
        """,
        (hours, hours, hours, age_days, minimum, bounded_limit(limit)),
    )
    return {
        "account_age_days": age_days,
        "lookback_hours": hours,
        "minimum_events": minimum,
        "candidates": rows,
        "count": len(rows),
    }


@mcp.tool()
async def search_accounts(
    status: Literal["active", "restricted", "banned"] | None = None,
    created_after: datetime | None = None,
    minimum_activity_score: float | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search accounts using bounded, allow-listed filters; never executes caller SQL."""
    rows = await fetch_all(
        """
        SELECT id, created_at, status, activity_score, kyc_status, bot_check_score, attributes
        FROM accounts
        WHERE (%s::text IS NULL OR status = %s)
          AND (%s::timestamptz IS NULL OR created_at >= %s)
          AND (%s::double precision IS NULL OR activity_score >= %s)
        ORDER BY activity_score DESC NULLS LAST, created_at DESC
        LIMIT %s
        """,
        (status, status, created_after, created_after, minimum_activity_score,
         minimum_activity_score, bounded_limit(limit)),
    )
    return {"accounts": rows, "count": len(rows)}


@mcp.tool()
async def sample_accounts(
    created_within_days: int = 30,
    status: Literal["active", "restricted", "banned"] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return a bounded random account sample for unbiased Patrol exploration."""
    days = max(1, min(created_within_days, 365))
    rows = await fetch_all(
        """
        SELECT id, created_at, status, activity_score, kyc_status, bot_check_score, attributes
        FROM accounts
        WHERE created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
          AND (%s::text IS NULL OR status = %s)
        ORDER BY RANDOM()
        LIMIT %s
        """,
        (days, status, status, bounded_limit(limit)),
    )
    return {"created_within_days": days, "accounts": rows, "count": len(rows)}


@mcp.tool()
async def get_account_activity(account_id: str, limit_per_type: int = 20) -> dict[str, Any]:
    """Get recent login, report, product, transaction, and message activity for one account."""
    limit = bounded_limit(limit_per_type)
    account = await fetch_one(
        "SELECT id, created_at, status, activity_score, kyc_status, bot_check_score, attributes "
        "FROM accounts WHERE id = %s",
        (account_id,),
    )
    if account is None:
        return {"found": False, "account_id": account_id}

    logins = await fetch_all(
        "SELECT id, ip_address::text AS ip_address, device_id, occurred_at, attributes "
        "FROM visible_login_events WHERE account_id = %s ORDER BY occurred_at DESC LIMIT %s",
        (account_id, limit),
    )
    reports = await fetch_all(
        "SELECT id, type, reason, status, created_at, attributes FROM visible_report_records "
        "WHERE target_account_id = %s ORDER BY created_at DESC LIMIT %s",
        (account_id, limit),
    )
    products = await fetch_all(
        "SELECT id, shop_id, title, description, image_urls, price, created_at, attributes "
        "FROM visible_products WHERE seller_account_id = %s ORDER BY created_at DESC LIMIT %s",
        (account_id, limit),
    )
    transactions = await fetch_all(
        "SELECT id, buyer_account_id, seller_account_id, product_id, payment_method, quantity, "
        "amount, status, created_at, attributes FROM transactions "
        "WHERE buyer_account_id = %s OR seller_account_id = %s ORDER BY created_at DESC LIMIT %s",
        (account_id, account_id, limit),
    )
    messages = await fetch_all(
        "SELECT id, conversation_id, sender_account_id, recipient_account_id, text, image_urls, "
        "urls, created_at, attributes FROM visible_messages WHERE sender_account_id = %s OR "
        "recipient_account_id = %s ORDER BY created_at DESC LIMIT %s",
        (account_id, account_id, limit),
    )
    return {
        "found": True,
        "account": account,
        "logins": logins,
        "reports": reports,
        "products": products,
        "transactions": transactions,
        "messages": messages,
    }


@mcp.tool()
async def find_shared_ip_accounts(
    account_id: str,
    lookback_days: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts sharing an IP with the subject and return login event evidence IDs."""
    days = max(1, min(lookback_days, 365))
    rows = await fetch_all(
        """
        SELECT subject.ip_address::text AS shared_ip, peer.account_id,
               ARRAY_AGG(DISTINCT peer.id) AS evidence_refs,
               MAX(peer.occurred_at) AS last_seen_at,
               COUNT(*) AS occurrence_count
        FROM visible_login_events subject
        JOIN visible_login_events peer ON peer.ip_address = subject.ip_address
        WHERE subject.account_id = %s
          AND peer.account_id <> %s
          AND subject.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
          AND peer.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        GROUP BY subject.ip_address, peer.account_id
        ORDER BY last_seen_at DESC
        LIMIT %s
        """,
        (account_id, account_id, days, days, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


@mcp.tool()
async def find_shared_device_accounts(
    account_id: str,
    lookback_days: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts sharing a device with the subject and return login event evidence IDs."""
    days = max(1, min(lookback_days, 365))
    rows = await fetch_all(
        """
        SELECT subject.device_id AS shared_device, peer.account_id,
               ARRAY_AGG(DISTINCT peer.id) AS evidence_refs,
               MAX(peer.occurred_at) AS last_seen_at,
               COUNT(*) AS occurrence_count
        FROM visible_login_events subject
        JOIN visible_login_events peer ON peer.device_id = subject.device_id
        WHERE subject.account_id = %s
          AND peer.account_id <> %s
          AND subject.device_id IS NOT NULL
          AND subject.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
          AND peer.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        GROUP BY subject.device_id, peer.account_id
        ORDER BY last_seen_at DESC
        LIMIT %s
        """,
        (account_id, account_id, days, days, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


@mcp.tool()
async def get_subject_association_seeds(
    subject_type: Literal["account", "shop", "product"],
    subject_id: str,
    lookback_days: int = 30,
    limit_per_type: int = 30,
) -> dict[str, Any]:
    """Collect bounded, evidence-bearing indicators around an association seed."""
    days = max(1, min(lookback_days, 365))
    limit = bounded_limit(limit_per_type)
    if subject_type == "account":
        subject = await fetch_one(
            "SELECT id, created_at, status, attributes FROM accounts WHERE id = %s",
            (subject_id,),
        )
        indicators = await fetch_all(
            """
            SELECT 'ip' AS type, host(ip_address) AS value,
                   'ip:' || host(ip_address) AS entity_id,
                   COUNT(*) AS occurrence_count, MIN(occurred_at) AS first_seen_at,
                   MAX(occurred_at) AS last_seen_at,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs
            FROM visible_login_events
            WHERE account_id = %s AND occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY ip_address
            UNION ALL
            SELECT 'device', device_id, 'device:' || device_id,
                   COUNT(*), MIN(occurred_at), MAX(occurred_at),
                   ARRAY_AGG(DISTINCT id ORDER BY id)
            FROM visible_login_events
            WHERE account_id = %s AND device_id IS NOT NULL
              AND occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY device_id
            ORDER BY last_seen_at DESC
            LIMIT %s
            """,
            (subject_id, days, subject_id, days, limit),
        )
        shops = await fetch_all(
            "SELECT id, owner_account_id, name, status, attributes FROM shops "
            "WHERE owner_account_id = %s LIMIT %s",
            (subject_id, limit),
        )
        counterparties = await fetch_all(
            """
            SELECT CASE WHEN buyer_account_id = %s THEN seller_account_id
                        ELSE buyer_account_id END AS account_id,
                   COUNT(*) AS occurrence_count, SUM(amount) AS total_amount,
                   MIN(created_at) AS first_seen_at, MAX(created_at) AS last_seen_at,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs
            FROM transactions
            WHERE (buyer_account_id = %s OR seller_account_id = %s)
              AND created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (subject_id, subject_id, subject_id, days, limit),
        )
        return {
            "found": subject is not None,
            "subject": subject,
            "indicators": indicators,
            "shops": shops,
            "transaction_counterparties": counterparties,
        }
    if subject_type == "shop":
        subject = await fetch_one(
            "SELECT id, owner_account_id, name, status, attributes FROM shops WHERE id = %s",
            (subject_id,),
        )
        products = await fetch_all(
            "SELECT id, shop_id, seller_account_id, title, price, created_at, attributes "
            "FROM visible_products WHERE shop_id = %s ORDER BY created_at DESC LIMIT %s",
            (subject_id, limit),
        )
        return {"found": subject is not None, "subject": subject, "products": products}
    subject = await fetch_one(
        "SELECT id, shop_id, seller_account_id, title, price, created_at, attributes "
        "FROM visible_products WHERE id = %s",
        (subject_id,),
    )
    buyers = await fetch_all(
        "SELECT buyer_account_id AS account_id, COUNT(*) AS occurrence_count, "
        "ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs, "
        "MIN(created_at) AS first_seen_at, MAX(created_at) AS last_seen_at "
        "FROM transactions WHERE product_id = %s GROUP BY buyer_account_id "
        "ORDER BY occurrence_count DESC LIMIT %s",
        (subject_id, limit),
    )
    return {"found": subject is not None, "subject": subject, "buyers": buyers}


async def _find_accounts_by_indicator(
    indicator_type: Literal["ip", "device", "shop", "product", "url", "domain"],
    indicator_value: str,
    lookback_days: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts linked to one exact indicator without accepting arbitrary SQL."""
    days = max(1, min(lookback_days, 365))
    bounded = bounded_limit(limit)
    if indicator_type in {"ip", "device"}:
        predicate = "ip_address = %s::inet" if indicator_type == "ip" else "device_id = %s"
        rows = await fetch_all(
            f"""
            SELECT account_id, COUNT(*) AS occurrence_count,
                   MIN(occurred_at) AS first_seen_at, MAX(occurred_at) AS last_seen_at,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs
            FROM visible_login_events WHERE {predicate}
              AND occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (indicator_value, days, bounded),
        )
    elif indicator_type == "shop":
        rows = await fetch_all(
            """
            SELECT account_id, COUNT(*) AS occurrence_count,
                   ARRAY_AGG(DISTINCT evidence_id ORDER BY evidence_id) AS evidence_refs
            FROM (
              SELECT owner_account_id AS account_id, id AS evidence_id FROM shops WHERE id = %s
              UNION ALL
              SELECT seller_account_id, id FROM products WHERE shop_id = %s
            ) links GROUP BY account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (indicator_value, indicator_value, bounded),
        )
    elif indicator_type == "product":
        rows = await fetch_all(
            """
            SELECT account_id, COUNT(*) AS occurrence_count,
                   ARRAY_AGG(DISTINCT evidence_id ORDER BY evidence_id) AS evidence_refs
            FROM (
              SELECT seller_account_id AS account_id, id AS evidence_id FROM products WHERE id = %s
              UNION ALL
              SELECT buyer_account_id, id FROM transactions WHERE product_id = %s
            ) links GROUP BY account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (indicator_value, indicator_value, bounded),
        )
    elif indicator_type == "url":
        rows = await fetch_all(
            """
            SELECT sender_account_id AS account_id, COUNT(*) AS occurrence_count,
                   MIN(created_at) AS first_seen_at, MAX(created_at) AS last_seen_at,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs
            FROM visible_messages WHERE urls ? %s
              AND created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY sender_account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (indicator_value, days, bounded),
        )
    else:
        rows = await fetch_all(
            """
            SELECT sender_account_id AS account_id, COUNT(*) AS occurrence_count,
                   MIN(created_at) AS first_seen_at, MAX(created_at) AS last_seen_at,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS evidence_refs
            FROM visible_messages, LATERAL jsonb_array_elements_text(urls) AS url(value)
            WHERE lower(split_part(regexp_replace(value, '^https?://', '', 'i'), '/', 1)) = lower(%s)
              AND created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
            GROUP BY sender_account_id ORDER BY occurrence_count DESC LIMIT %s
            """,
            (indicator_value, days, bounded),
        )
    return {
        "indicator": {"type": indicator_type, "value": indicator_value},
        "lookback_days": days,
        "accounts": rows,
        "count": len(rows),
    }


@mcp.tool()
async def find_accounts_by_indicator(
    indicator_type: Literal["ip", "device", "shop", "product", "url", "domain"],
    indicator_value: str,
    lookback_days: int = 30,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts linked to one exact indicator without accepting arbitrary SQL."""
    return await _find_accounts_by_indicator(
        indicator_type, indicator_value, lookback_days, limit
    )


@mcp.tool()
async def get_indicator_prevalence(
    indicator_type: Literal["ip", "device", "shop", "product", "url", "domain"],
    indicator_value: str,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Measure how common an indicator is so shared infrastructure is not over-weighted."""
    result = await _find_accounts_by_indicator(
        indicator_type=indicator_type,
        indicator_value=indicator_value,
        lookback_days=lookback_days,
        limit=100,
    )
    return {
        "indicator": result["indicator"],
        "lookback_days": result["lookback_days"],
        "distinct_account_count": len(result["accounts"]),
        "sample_truncated": len(result["accounts"]) == 100,
    }


@mcp.tool()
async def expand_association_graph(
    seed_entity_ids: list[str],
    max_hops: int = 2,
    max_nodes: int = 100,
) -> dict[str, Any]:
    """Expand a bounded, cycle-safe subgraph from explicit entity IDs."""
    seeds = list(dict.fromkeys(item for item in seed_entity_ids if item))[:20]
    hops = max(1, min(max_hops, 2))
    node_limit = max(1, min(max_nodes, 100))
    if not seeds:
        return {"nodes": [], "edges": [], "truncated": False}
    nodes = await fetch_all(
        """
        WITH RECURSIVE walk(node_id, depth, path) AS (
          SELECT id, 0, ARRAY[id] FROM entities WHERE id = ANY(%s)
          UNION ALL
          SELECT CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END,
                 w.depth + 1,
                 w.path || CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END
          FROM walk w JOIN relationships r
            ON r.source_id = w.node_id OR r.target_id = w.node_id
          WHERE w.depth < %s
            AND NOT (CASE WHEN r.source_id = w.node_id THEN r.target_id ELSE r.source_id END = ANY(w.path))
        )
        SELECT e.id, e.type, e.label, e.attributes, MIN(w.depth) AS depth
        FROM walk w JOIN entities e ON e.id = w.node_id
        GROUP BY e.id ORDER BY depth, e.id LIMIT %s
        """,
        (seeds, hops, node_limit + 1),
    )
    truncated = len(nodes) > node_limit
    nodes = nodes[:node_limit]
    node_ids = [row["id"] for row in nodes]
    edges = await fetch_all(
        """
        SELECT source_id AS source, target_id AS target, type, value, confidence,
               evidence_refs, first_seen_at, last_seen_at
        FROM relationships
        WHERE source_id = ANY(%s) AND target_id = ANY(%s)
        ORDER BY last_seen_at DESC NULLS LAST LIMIT 200
        """,
        (node_ids, node_ids),
    )
    return {"nodes": nodes, "edges": edges, "truncated": truncated}


@mcp.tool()
async def get_environment_overview() -> dict[str, Any]:
    """Return simulation time and bounded marketplace table counts from Environment."""
    state = await fetch_one(
        "SELECT simulation_time, initial_time, scenario_name, updated_at "
        "FROM simulation_state WHERE singleton_id = 1"
    )
    counts = await fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM accounts) AS accounts,
          (SELECT COUNT(*) FROM shops) AS shops,
          (SELECT COUNT(*) FROM products) AS products,
          (SELECT COUNT(*) FROM transactions) AS transactions,
          (SELECT COUNT(*) FROM visible_messages) AS messages,
          (SELECT COUNT(*) FROM visible_payment_attempts) AS payment_attempts,
          (SELECT COUNT(*) FROM visible_refunds) AS refunds,
          (SELECT COUNT(*) FROM visible_disputes) AS disputes
        """
    )
    return {"simulation": state, "counts": counts or {}}


@mcp.tool()
async def find_shared_payment_instrument_accounts(
    account_id: str,
    lookback_days: int = 90,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts using the same hashed payment instrument as a seed account."""
    days = max(1, min(lookback_days, 365))
    rows = await fetch_all(
        """
        SELECT seed.payment_instrument_hash, peer.payer_account_id AS account_id,
               COUNT(*) AS occurrence_count,
               MIN(peer.occurred_at) AS first_seen_at,
               MAX(peer.occurred_at) AS last_seen_at,
               ARRAY_AGG(DISTINCT peer.id ORDER BY peer.id) AS evidence_refs
        FROM visible_payment_attempts seed
        JOIN visible_payment_attempts peer
          ON peer.payment_instrument_hash = seed.payment_instrument_hash
        WHERE seed.payer_account_id = %s
          AND peer.payer_account_id <> %s
          AND seed.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
          AND peer.occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        GROUP BY seed.payment_instrument_hash, peer.payer_account_id
        ORDER BY occurrence_count DESC, last_seen_at DESC LIMIT %s
        """,
        (account_id, account_id, days, days, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


@mcp.tool()
async def find_reused_product_image_accounts(
    account_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Find other sellers whose products reuse an exact image hash from the seed seller."""
    rows = await fetch_all(
        """
        SELECT seed_image.image_hash, peer_product.seller_account_id AS account_id,
               ARRAY_AGG(DISTINCT peer_image.id ORDER BY peer_image.id) AS evidence_refs,
               ARRAY_AGG(DISTINCT peer_product.id ORDER BY peer_product.id) AS product_ids,
               MIN(peer_image.created_at) AS first_seen_at,
               MAX(peer_image.created_at) AS last_seen_at
        FROM products seed_product
        JOIN product_images seed_image ON seed_image.product_id = seed_product.id
        JOIN product_images peer_image ON peer_image.image_hash = seed_image.image_hash
        JOIN products peer_product ON peer_product.id = peer_image.product_id
        WHERE seed_product.seller_account_id = %s
          AND peer_product.seller_account_id <> %s
          AND seed_image.created_at <= (SELECT simulation_time FROM simulation_state)
          AND peer_image.created_at <= (SELECT simulation_time FROM simulation_state)
        GROUP BY seed_image.image_hash, peer_product.seller_account_id
        ORDER BY last_seen_at DESC LIMIT %s
        """,
        (account_id, account_id, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


@mcp.tool()
async def get_account_commerce_links(
    account_id: str,
    lookback_days: int = 90,
    limit_per_type: int = 50,
) -> dict[str, Any]:
    """Return evidence-bearing transaction, refund, dispute, and review links for an account."""
    days = max(1, min(lookback_days, 365))
    limit = bounded_limit(limit_per_type)
    transactions = await fetch_all(
        """
        SELECT id, buyer_account_id, seller_account_id, product_id, amount, currency,
               status, created_at, attributes
        FROM transactions
        WHERE (buyer_account_id = %s OR seller_account_id = %s)
          AND created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        ORDER BY created_at DESC LIMIT %s
        """,
        (account_id, account_id, days, limit),
    )
    refunds = await fetch_all(
        """
        SELECT r.id, r.transaction_id, r.requester_account_id, r.reason, r.amount,
               r.status, r.requested_at, t.buyer_account_id, t.seller_account_id
        FROM visible_refunds r JOIN transactions t ON t.id = r.transaction_id
        WHERE (r.requester_account_id = %s OR t.seller_account_id = %s)
          AND r.requested_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        ORDER BY r.requested_at DESC LIMIT %s
        """,
        (account_id, account_id, days, limit),
    )
    disputes = await fetch_all(
        """
        SELECT d.id, d.transaction_id, d.opened_by_account_id, d.reason, d.status,
               d.created_at, t.buyer_account_id, t.seller_account_id
        FROM visible_disputes d JOIN transactions t ON t.id = d.transaction_id
        WHERE (d.opened_by_account_id = %s OR t.seller_account_id = %s)
          AND d.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        ORDER BY d.created_at DESC LIMIT %s
        """,
        (account_id, account_id, days, limit),
    )
    reviews = await fetch_all(
        """
        SELECT r.id, r.product_id, r.transaction_id, r.reviewer_account_id,
               r.rating, r.created_at, p.seller_account_id
        FROM reviews r JOIN products p ON p.id = r.product_id
        WHERE (r.reviewer_account_id = %s OR p.seller_account_id = %s)
          AND r.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        ORDER BY r.created_at DESC LIMIT %s
        """,
        (account_id, account_id, days, limit),
    )
    return {
        "account_id": account_id,
        "lookback_days": days,
        "transactions": transactions,
        "refunds": refunds,
        "disputes": disputes,
        "reviews": reviews,
    }


@mcp.tool()
async def find_conversation_accounts(
    account_id: str,
    lookback_days: int = 90,
    limit: int = 50,
) -> dict[str, Any]:
    """Find accounts sharing conversations with the seed and return message evidence IDs."""
    days = max(1, min(lookback_days, 365))
    rows = await fetch_all(
        """
        SELECT peer.account_id, peer.participant_role,
               COUNT(DISTINCT peer.conversation_id) AS conversation_count,
               ARRAY_REMOVE(ARRAY_AGG(DISTINCT m.id ORDER BY m.id), NULL) AS evidence_refs,
               MIN(m.created_at) AS first_seen_at, MAX(m.created_at) AS last_seen_at
        FROM conversation_participants seed
        JOIN conversation_participants peer
          ON peer.conversation_id = seed.conversation_id AND peer.account_id <> seed.account_id
        LEFT JOIN visible_messages m ON m.conversation_id = seed.conversation_id
          AND m.created_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day')
        WHERE seed.account_id = %s
        GROUP BY peer.account_id, peer.participant_role
        ORDER BY conversation_count DESC, last_seen_at DESC LIMIT %s
        """,
        (days, account_id, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


@mcp.tool()
async def get_account_security_timeline(
    account_id: str,
    lookback_days: int = 90,
    limit: int = 50,
) -> dict[str, Any]:
    """Return login and account-security events useful for takeover and coordination analysis."""
    days = max(1, min(lookback_days, 365))
    bounded = bounded_limit(limit)
    security_events = await fetch_all(
        "SELECT id, event_type, occurred_at, attributes FROM visible_account_security_events "
        "WHERE account_id = %s AND occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day') "
        "ORDER BY occurred_at DESC LIMIT %s",
        (account_id, days, bounded),
    )
    status_events = await fetch_all(
        "SELECT id, status, reason, occurred_at FROM visible_account_status_events "
        "WHERE account_id = %s AND occurred_at >= (SELECT simulation_time FROM simulation_state) - (%s * INTERVAL '1 day') "
        "ORDER BY occurred_at DESC LIMIT %s",
        (account_id, days, bounded),
    )
    return {
        "account_id": account_id,
        "lookback_days": days,
        "security_events": security_events,
        "status_events": status_events,
    }


@mcp.tool()
async def get_entity_neighbors(entity_id: str, limit: int = 50) -> dict[str, Any]:
    """Return one-hop association graph nodes and evidence-bearing edges for an entity."""
    nodes = await fetch_all(
        """
        SELECT DISTINCT e.id, e.type, e.label, e.attributes
        FROM relationships r
        JOIN entities e ON e.id = CASE WHEN r.source_id = %s THEN r.target_id ELSE r.source_id END
        WHERE r.source_id = %s OR r.target_id = %s
        LIMIT %s
        """,
        (entity_id, entity_id, entity_id, bounded_limit(limit)),
    )
    edges = await fetch_all(
        """
        SELECT source_id AS source, target_id AS target, type, value, confidence, evidence_refs,
               first_seen_at, last_seen_at
        FROM relationships WHERE source_id = %s OR target_id = %s
        ORDER BY last_seen_at DESC NULLS LAST LIMIT %s
        """,
        (entity_id, entity_id, bounded_limit(limit)),
    )
    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}


@mcp.tool()
async def get_previous_cases(
    subject_type: str,
    subject_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Get prior cases for a subject so an agent can avoid duplicate discoveries."""
    rows = await fetch_all(
        """
        SELECT id, source, subject_type, subject_id, status, risk_score, trigger_reason,
               created_at, updated_at, attributes
        FROM cases WHERE subject_type = %s AND subject_id = %s
        ORDER BY created_at DESC LIMIT %s
        """,
        (subject_type, subject_id, bounded_limit(limit)),
    )
    return {"cases": rows, "count": len(rows)}


@mcp.tool()
async def get_evidence_records(evidence_ids: list[str]) -> dict[str, Any]:
    """Resolve record IDs into canonical Evidence objects for agent results."""
    ids = list(dict.fromkeys(item for item in evidence_ids if item))[:100]
    if not ids:
        return {"evidence": [], "missing_ids": []}
    rows = await fetch_all(
        """
        SELECT id, 'environment' AS source, 'login_event' AS type,
               account_id AS ref_id, occurred_at AS observed_at,
               jsonb_build_object('account_id', account_id,
                                  'ip_address', ip_address::text,
                                  'device_id', device_id,
                                  'attributes', attributes) AS data
        FROM visible_login_events WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', type, target_account_id, created_at,
               jsonb_build_object('target_account_id', target_account_id,
                                  'reason', reason, 'status', status,
                                  'attributes', attributes)
        FROM visible_report_records WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'investigation', 'previous_case', subject_id, created_at,
               jsonb_build_object('case_id', id, 'source', source,
                                  'subject_type', subject_type,
                                  'subject_id', subject_id, 'status', status,
                                  'risk_score', risk_score,
                                  'trigger_reason', trigger_reason)
        FROM cases WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'product', seller_account_id, created_at,
               jsonb_build_object('shop_id', shop_id, 'seller_account_id', seller_account_id,
                                  'title', title, 'price', price, 'attributes', attributes)
        FROM visible_products WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'transaction', seller_account_id, created_at,
               jsonb_build_object('buyer_account_id', buyer_account_id,
                                  'seller_account_id', seller_account_id,
                                  'product_id', product_id, 'amount', amount,
                                  'status', status, 'attributes', attributes)
        FROM transactions WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'message', sender_account_id, created_at,
               jsonb_build_object('conversation_id', conversation_id,
                                  'sender_account_id', sender_account_id,
                                  'recipient_account_id', recipient_account_id,
                                  'urls', urls, 'attributes', attributes)
        FROM visible_messages WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'shop', owner_account_id, NULL,
               jsonb_build_object('owner_account_id', owner_account_id,
                                  'name', name, 'status', status, 'attributes', attributes)
        FROM shops WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'payment_attempt', payer_account_id, occurred_at,
               jsonb_build_object('transaction_id', transaction_id,
                                  'payer_account_id', payer_account_id,
                                  'payment_method', payment_method,
                                  'payment_instrument_hash', payment_instrument_hash,
                                  'status', status, 'failure_code', failure_code,
                                  'device_id', device_id, 'ip_address', ip_address::text)
        FROM visible_payment_attempts WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'product_image', product_id, created_at,
               jsonb_build_object('product_id', product_id, 'image_url', image_url,
                                  'image_hash', image_hash)
        FROM product_images WHERE id = ANY(%s)
          AND created_at <= (SELECT simulation_time FROM simulation_state)
        UNION ALL
        SELECT id, 'environment', 'refund', requester_account_id, requested_at,
               jsonb_build_object('transaction_id', transaction_id,
                                  'requester_account_id', requester_account_id,
                                  'reason', reason, 'amount', amount, 'status', status)
        FROM visible_refunds WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'dispute', opened_by_account_id, created_at,
               jsonb_build_object('transaction_id', transaction_id,
                                  'opened_by_account_id', opened_by_account_id,
                                  'reason', reason, 'status', status)
        FROM visible_disputes WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', 'account_security_event', account_id, occurred_at,
               jsonb_build_object('account_id', account_id, 'event_type', event_type,
                                  'attributes', attributes)
        FROM visible_account_security_events WHERE id = ANY(%s)
        """,
        (ids, ids, ids, ids, ids, ids, ids, ids, ids, ids, ids, ids),
    )
    found_ids = {row["id"] for row in rows}
    return {
        "evidence": rows,
        "missing_ids": [item for item in ids if item not in found_ids],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
