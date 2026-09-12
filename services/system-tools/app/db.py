from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from typing import Any, AsyncIterator

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://fraud:fraud_dev_password@localhost:5432/fraud_intelligence",
    )


pool = AsyncConnectionPool(
    conninfo=_database_url(),
    min_size=1,
    max_size=int(os.environ.get("DATABASE_POOL_SIZE", "5")),
    open=False,
    kwargs={"row_factory": dict_row},
)


@asynccontextmanager
async def connection() -> AsyncIterator[Any]:
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        yield conn


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date, Decimal, IPv4Address, IPv6Address)):
        return str(value)
    return value


async def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    async with connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, params)
            return json_safe(await cursor.fetchall())


async def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    async with connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, params)
            return json_safe(await cursor.fetchone())
