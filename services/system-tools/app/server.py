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
           WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')) AS new_account_count,
          (SELECT COUNT(*) FROM login_events
           WHERE occurred_at >= NOW() - (%s * INTERVAL '1 hour')) AS login_count,
          (SELECT COUNT(DISTINCT ip_address) FROM login_events
           WHERE occurred_at >= NOW() - (%s * INTERVAL '1 hour')) AS distinct_ip_count,
          (SELECT COUNT(*) FROM products
           WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')) AS product_count,
          (SELECT COUNT(*) FROM messages
           WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')) AS message_count,
          (SELECT COUNT(*) FROM report_records
           WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')) AS report_count,
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
        FROM login_events
        WHERE occurred_at >= NOW() - (%s * INTERVAL '1 hour')
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
          LEFT JOIN login_events l ON l.account_id = a.id
            AND l.occurred_at >= NOW() - (%s * INTERVAL '1 hour')
          LEFT JOIN products p ON p.seller_account_id = a.id
            AND p.created_at >= NOW() - (%s * INTERVAL '1 hour')
          LEFT JOIN messages m ON m.sender_account_id = a.id
            AND m.created_at >= NOW() - (%s * INTERVAL '1 hour')
          WHERE a.created_at >= NOW() - (%s * INTERVAL '1 day')
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
        WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
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
        "FROM login_events WHERE account_id = %s ORDER BY occurred_at DESC LIMIT %s",
        (account_id, limit),
    )
    reports = await fetch_all(
        "SELECT id, type, reason, status, created_at, attributes FROM report_records "
        "WHERE target_account_id = %s ORDER BY created_at DESC LIMIT %s",
        (account_id, limit),
    )
    products = await fetch_all(
        "SELECT id, shop_id, title, description, image_urls, price, created_at, attributes "
        "FROM products WHERE seller_account_id = %s ORDER BY created_at DESC LIMIT %s",
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
        "urls, created_at, attributes FROM messages WHERE sender_account_id = %s OR "
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
        FROM login_events subject
        JOIN login_events peer ON peer.ip_address = subject.ip_address
        WHERE subject.account_id = %s
          AND peer.account_id <> %s
          AND subject.occurred_at >= NOW() - (%s * INTERVAL '1 day')
          AND peer.occurred_at >= NOW() - (%s * INTERVAL '1 day')
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
        FROM login_events subject
        JOIN login_events peer ON peer.device_id = subject.device_id
        WHERE subject.account_id = %s
          AND peer.account_id <> %s
          AND subject.device_id IS NOT NULL
          AND subject.occurred_at >= NOW() - (%s * INTERVAL '1 day')
          AND peer.occurred_at >= NOW() - (%s * INTERVAL '1 day')
        GROUP BY subject.device_id, peer.account_id
        ORDER BY last_seen_at DESC
        LIMIT %s
        """,
        (account_id, account_id, days, days, bounded_limit(limit)),
    )
    return {"subject_account_id": account_id, "matches": rows, "count": len(rows)}


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
    """Resolve record IDs into canonical Evidence objects for a PatrolResult."""
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
        FROM login_events WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'environment', type, target_account_id, created_at,
               jsonb_build_object('target_account_id', target_account_id,
                                  'reason', reason, 'status', status,
                                  'attributes', attributes)
        FROM report_records WHERE id = ANY(%s)
        UNION ALL
        SELECT id, 'investigation', 'previous_case', subject_id, created_at,
               jsonb_build_object('case_id', id, 'source', source,
                                  'subject_type', subject_type,
                                  'subject_id', subject_id, 'status', status,
                                  'risk_score', risk_score,
                                  'trigger_reason', trigger_reason)
        FROM cases WHERE id = ANY(%s)
        """,
        (ids, ids, ids),
    )
    found_ids = {row["id"] for row in rows}
    return {
        "evidence": rows,
        "missing_ids": [item for item in ids if item not in found_ids],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
