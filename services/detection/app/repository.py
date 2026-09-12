from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.domain.context import DetectionContext
from app.domain.models import Evidence, Subject


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, Decimal, IPv4Address, IPv6Address)):
        return str(value)
    return value


class PostgresDetectionRepository:
    """Read-only, parameterized access to replay-visible Environment data."""

    def __init__(self, database_url: str, pool_size: int = 5) -> None:
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=pool_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def _open(self) -> None:
        if self.pool.closed:
            await self.pool.open()

    async def close(self) -> None:
        if not self.pool.closed:
            await self.pool.close()

    async def health(self) -> bool:
        await self._open()
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                return (await cursor.fetchone()) is not None

    async def _fetch_all(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        await self._open()
        async with self.pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(query, params)
                return list(await cursor.fetchall())

    async def _resolve_accounts(self, subject: Subject) -> list[str] | None:
        queries = {
            "account": (
                "SELECT ARRAY[id] AS account_ids FROM accounts "
                "WHERE id = %s AND created_at <= (SELECT simulation_time FROM simulation_state WHERE singleton_id = 1)"
            ),
            "shop": (
                "SELECT ARRAY[owner_account_id] AS account_ids FROM shops "
                "WHERE id = %s AND created_at <= (SELECT simulation_time FROM simulation_state WHERE singleton_id = 1)"
            ),
            "product": (
                "SELECT ARRAY[seller_account_id] AS account_ids FROM products "
                "WHERE id = %s AND created_at <= (SELECT simulation_time FROM simulation_state WHERE singleton_id = 1)"
            ),
            "transaction": (
                "SELECT ARRAY[buyer_account_id, seller_account_id] AS account_ids FROM transactions "
                "WHERE id = %s AND created_at <= (SELECT simulation_time FROM simulation_state WHERE singleton_id = 1)"
            ),
            "order": (
                "SELECT ARRAY[buyer_account_id, seller_account_id] AS account_ids FROM transactions "
                "WHERE id = %s AND created_at <= (SELECT simulation_time FROM simulation_state WHERE singleton_id = 1)"
            ),
            "message": (
                "SELECT ARRAY_REMOVE(ARRAY[sender_account_id, recipient_account_id], NULL) AS account_ids "
                "FROM visible_messages WHERE id = %s"
            ),
        }
        rows = await self._fetch_all(queries[subject.type], (subject.id,))
        return list(dict.fromkeys(rows[0]["account_ids"])) if rows else None

    @staticmethod
    def _evidence(kind: str, row: dict[str, Any], time_field: str | None) -> Evidence:
        values = dict(row)
        evidence_id = str(values.pop("id"))
        observed_at = values.pop(time_field, None) if time_field else None
        return Evidence(
            id=evidence_id,
            source="environment",
            type=kind,
            observed_at=observed_at,
            data=_json_safe(values),
        )

    async def load_context(self, subject: Subject, required_evidence: set[str] | None = None) -> DetectionContext | None:
        account_ids = await self._resolve_accounts(subject)
        if account_ids is None:
            return None

        required = required_evidence if required_evidence is not None else {"message","report_record","login_event","account_security_event","product","product_image","payment_attempt","delivery_event","refund","dispute"}
        evidence: list[Evidence] = []
        if "message" in required: evidence.extend(await self._load_messages(subject, account_ids))
        if "report_record" in required: evidence.extend(await self._load_reports(subject, account_ids))
        if required & {"login_event", "account_security_event"}: evidence.extend(await self._load_account_access(account_ids))
        if required & {"product", "product_image"}: evidence.extend(await self._load_products(subject, account_ids))
        if "payment_attempt" in required: evidence.extend(await self._load_payments(subject, account_ids))
        if "delivery_event" in required: evidence.extend(await self._load_delivery(subject, account_ids))
        if required & {"refund", "dispute"}: evidence.extend(await self._load_claims(subject, account_ids))
        row = await self._fetch_all("SELECT simulation_time FROM simulation_state WHERE singleton_id = 1")
        unique = {item.id: item for item in evidence}
        return DetectionContext(
            subject=subject,
            account_ids=account_ids,
            evidence=list(unique.values()),
            as_of=row[0]["simulation_time"] if row else None,
        )

    async def _load_messages(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        if subject.type == "message":
            where, params = "m.id = %s", (subject.id,)
        elif subject.type in {"transaction", "order"}:
            where, params = "c.transaction_id = %s", (subject.id,)
        elif subject.type == "shop":
            where, params = "c.shop_id = %s", (subject.id,)
        elif subject.type == "product":
            where, params = "t.product_id = %s", (subject.id,)
        else:
            where, params = "m.sender_account_id = ANY(%s)", (account_ids,)
        rows = await self._fetch_all(
            f"""
            SELECT m.id, m.conversation_id, m.sender_account_id,
                   m.recipient_account_id, m.text, m.urls, m.created_at
              FROM visible_messages m
              JOIN conversations c ON c.id = m.conversation_id
              LEFT JOIN transactions t ON t.id = c.transaction_id
             WHERE {where}
             ORDER BY m.created_at DESC LIMIT 100
            """,
            params,
        )
        return [self._evidence("message", row, "created_at") for row in rows]

    async def _load_reports(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        target_type = "transaction" if subject.type == "order" else subject.type
        rows = await self._fetch_all(
            """
            SELECT id, reporter_account_id, target_account_id, target_type,
                   target_id, type, reason, status, created_at
              FROM visible_report_records
             WHERE (target_type = %s AND target_id = %s)
                OR (%s = 'account' AND target_account_id = ANY(%s))
             ORDER BY created_at DESC LIMIT 100
            """,
            (target_type, subject.id, subject.type, account_ids),
        )
        return [self._evidence("report_record", row, "created_at") for row in rows]

    async def _load_account_access(self, account_ids: list[str]) -> list[Evidence]:
        logins = await self._fetch_all(
            """
            SELECT id, account_id, device_id, ip_address::text AS ip_address,
                   country_code, success, auth_method, occurred_at,
                   COALESCE((attributes->>'device_novel')::boolean, false) AS device_novel
              FROM visible_login_events
             WHERE account_id = ANY(%s)
             ORDER BY occurred_at DESC LIMIT 100
            """,
            (account_ids,),
        )
        security = await self._fetch_all(
            """
            SELECT id, account_id, event_type, occurred_at, attributes
              FROM visible_account_security_events
             WHERE account_id = ANY(%s)
             ORDER BY occurred_at DESC LIMIT 100
            """,
            (account_ids,),
        )
        return [self._evidence("login_event", row, "occurred_at") for row in logins] + [
            self._evidence("account_security_event", row, "occurred_at") for row in security
        ]

    async def _load_products(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        if subject.type == "product":
            where = """
                (p.seller_account_id = ANY(%s)
                 OR EXISTS (
                    SELECT 1
                      FROM product_images target_image
                      JOIN product_images peer_image
                        ON peer_image.image_hash = target_image.image_hash
                     WHERE target_image.product_id = %s
                       AND peer_image.product_id = p.id
                       AND target_image.created_at <= s.simulation_time
                       AND peer_image.created_at <= s.simulation_time
                 ))
            """
            params = (account_ids, subject.id)
        elif subject.type == "shop":
            where, params = "p.shop_id = %s", (subject.id,)
        else:
            where, params = "p.seller_account_id = ANY(%s)", (account_ids,)
        products = await self._fetch_all(
            f"""
            SELECT p.id, p.shop_id, p.seller_account_id, p.title, p.price,
                   p.currency, p.created_at
              FROM products p CROSS JOIN simulation_state s
             WHERE s.singleton_id = 1 AND p.created_at <= s.simulation_time
               AND {where}
             ORDER BY p.created_at DESC LIMIT 100
            """,
            params,
        )
        product_ids = [row["id"] for row in products]
        images = []
        if product_ids:
            images = await self._fetch_all(
                """
                SELECT pi.id, pi.product_id, pi.image_url, pi.image_hash, pi.created_at
                  FROM product_images pi CROSS JOIN simulation_state s
                 WHERE s.singleton_id = 1 AND pi.created_at <= s.simulation_time
                   AND pi.product_id = ANY(%s)
                 ORDER BY pi.created_at DESC LIMIT 200
                """,
                (product_ids,),
            )
        return [self._evidence("product", row, "created_at") for row in products] + [
            self._evidence("product_image", row, "created_at") for row in images
        ]

    async def _load_payments(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        if subject.type in {"transaction", "order"}:
            where, params = "p.transaction_id = %s", (subject.id,)
        else:
            where, params = "(t.buyer_account_id = ANY(%s) OR t.seller_account_id = ANY(%s))", (account_ids, account_ids)
        rows = await self._fetch_all(
            f"""
            SELECT p.id, p.transaction_id, p.payer_account_id, p.payment_method,
                   p.payment_instrument_hash, p.status, p.failure_code,
                   p.device_id, p.ip_address::text AS ip_address, p.occurred_at
              FROM visible_payment_attempts p
              JOIN transactions t ON t.id = p.transaction_id
             WHERE {where}
             ORDER BY p.occurred_at DESC LIMIT 100
            """,
            params,
        )
        return [self._evidence("payment_attempt", row, "occurred_at") for row in rows]

    async def _load_delivery(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        if subject.type in {"transaction", "order"}:
            where, params = "d.transaction_id = %s", (subject.id,)
        else:
            where = "(t.buyer_account_id = ANY(%s) OR t.seller_account_id = ANY(%s))"
            params = (account_ids, account_ids)
        rows = await self._fetch_all(
            f"""
            SELECT d.id, d.transaction_id, d.status, d.occurred_at, d.attributes
              FROM visible_delivery_events d
              JOIN transactions t ON t.id = d.transaction_id
             WHERE {where}
             ORDER BY d.occurred_at DESC LIMIT 100
            """,
            params,
        )
        return [self._evidence("delivery_event", row, "occurred_at") for row in rows]

    async def _load_claims(
        self, subject: Subject, account_ids: list[str]
    ) -> list[Evidence]:
        if subject.type in {"transaction", "order"}:
            refund_where = dispute_where = "transaction_id = %s"
            params: tuple[Any, ...] = (subject.id,)
        else:
            refund_where = "requester_account_id = ANY(%s)"
            dispute_where = "opened_by_account_id = ANY(%s)"
            params = (account_ids,)
        refunds = await self._fetch_all(
            f"SELECT id, transaction_id, requester_account_id, reason, status, requested_at "
            f"FROM visible_refunds WHERE {refund_where} ORDER BY requested_at DESC LIMIT 100",
            params,
        )
        disputes = await self._fetch_all(
            f"SELECT id, transaction_id, opened_by_account_id, reason, status, created_at "
            f"FROM visible_disputes WHERE {dispute_where} ORDER BY created_at DESC LIMIT 100",
            params,
        )
        return [self._evidence("refund", row, "requested_at") for row in refunds] + [
            self._evidence("dispute", row, "created_at") for row in disputes
        ]
