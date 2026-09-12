from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import DetectionPolicy
import psycopg
from psycopg.rows import dict_row


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PolicyNotFoundError(LookupError):
    pass


class FilePolicyRepository:
    def __init__(self, policy_dir: str | Path, database_url: str | None = None) -> None:
        self.policy_dir = Path(policy_dir)
        self._cache: dict[str, DetectionPolicy] = {}
        self.database_url = database_url

    async def initialize(self) -> None:
        if not self.database_url:
            return
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('agent-control-schema'))")
            await conn.execute("""CREATE TABLE IF NOT EXISTS agent_policies(
              agent TEXT NOT NULL, strategy TEXT NOT NULL, version TEXT NOT NULL,
              document JSONB NOT NULL, active BOOLEAN NOT NULL DEFAULT false,
              source TEXT NOT NULL DEFAULT 'human', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY(agent,strategy,version));
              CREATE UNIQUE INDEX IF NOT EXISTS agent_policies_one_active_idx ON agent_policies(agent,strategy) WHERE active;""")
            await conn.execute("ALTER TABLE agent_policies DROP CONSTRAINT IF EXISTS agent_policies_agent_check")
            await conn.execute(
                "ALTER TABLE agent_policies ADD CONSTRAINT "
                "agent_policies_agent_check "
                "CHECK (agent IN ('patrol','association','detection'))"
            )

    def _from_database(self, version: str) -> DetectionPolicy | None:
        if not self.database_url:
            return None
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                row = conn.execute("SELECT document FROM agent_policies WHERE agent='detection' AND strategy='default' AND version=%s", (version,)).fetchone()
                return DetectionPolicy.model_validate(row["document"]) if row else None
        except psycopg.Error:
            return None

    def active_version(self) -> str | None:
        if not self.database_url:
            return None
        try:
            with psycopg.connect(self.database_url) as conn:
                row = conn.execute("SELECT version FROM agent_policies WHERE agent='detection' AND strategy='default' AND active").fetchone()
                return str(row[0]) if row else None
        except psycopg.Error:
            return None

    def resolve(self, version: str) -> DetectionPolicy:
        if not _SAFE_VERSION.fullmatch(version):
            raise PolicyNotFoundError(version)
        if version in self._cache:
            return self._cache[version]
        stored = self._from_database(version)
        if stored is not None:
            self._cache[version] = stored
            return stored
        policy = DetectionPolicy.model_validate(self.read_document(version))
        self._cache[version] = policy
        return policy

    def read_document(self, version: str) -> dict[str, Any]:
        """Read an uncoerced policy document for cross-validator boundaries."""

        if not _SAFE_VERSION.fullmatch(version):
            raise PolicyNotFoundError(version)
        path = self.policy_dir / f"{version}.json"
        if not path.is_file():
            raise PolicyNotFoundError(version)
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"Policy file {version!r} must contain a JSON object")
        if document.get("version") != version:
            raise ValueError(
                f"Policy file version {document.get('version')!r} does not match "
                f"{version!r}"
            )
        return document

    async def list_versions(self) -> list[dict]:
        if not self.database_url:
            return []
        async with await psycopg.AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    "SELECT version, document, active, source, created_at "
                    "FROM agent_policies WHERE agent='detection' AND strategy='default' "
                    "ORDER BY created_at DESC"
                )
            ).fetchall()
            return list(rows)

    async def save_draft(self, policy: DetectionPolicy, source: str) -> bool:
        if not self.database_url:
            return False
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            result = await conn.execute(
                "INSERT INTO agent_policies(agent,strategy,version,document,active,source) "
                "VALUES('detection','default',%s,%s::jsonb,false,%s) ON CONFLICT DO NOTHING",
                (policy.version, json.dumps(policy.model_dump(mode="json")), source),
            )
            return result.rowcount == 1

    async def publish(self, policy: DetectionPolicy, source: str) -> bool:
        if not self.database_url:
            return False
        document = policy.model_dump(mode="json")
        async with await psycopg.AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            async with conn.transaction():
                existing = await (await conn.execute("SELECT document FROM agent_policies WHERE agent='detection' AND strategy='default' AND version=%s", (policy.version,))).fetchone()
                if existing and existing["document"] != document:
                    return False
                await conn.execute("UPDATE agent_policies SET active=false WHERE agent='detection' AND strategy='default'")
                if existing:
                    await conn.execute(
                        "UPDATE agent_policies SET active=true "
                        "WHERE agent='detection' AND strategy='default' AND version=%s",
                        (policy.version,),
                    )
                else:
                    await conn.execute(
                        "INSERT INTO agent_policies(agent,strategy,version,document,active,source) "
                        "VALUES('detection','default',%s,%s::jsonb,true,%s)",
                        (policy.version, json.dumps(document), source),
                    )
        self._cache.pop(policy.version, None)
        return True

    async def activate(self, version: str) -> bool:
        if not self.database_url:
            return False
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            async with conn.transaction():
                exists = await (await conn.execute("SELECT 1 FROM agent_policies WHERE agent='detection' AND strategy='default' AND version=%s", (version,))).fetchone()
                if not exists:
                    return False
                await conn.execute("UPDATE agent_policies SET active=false WHERE agent='detection' AND strategy='default'")
                await conn.execute("UPDATE agent_policies SET active=true WHERE agent='detection' AND strategy='default' AND version=%s", (version,))
                return True


class LayeredFilePolicyRepository:
    """Resolve immutable policies across non-overlapping read-only directories."""

    def __init__(
        self,
        policy_dirs: tuple[str | Path, ...] | list[str | Path],
        database_url: str | None = None,
    ) -> None:
        if not policy_dirs:
            raise ValueError("At least one policy directory is required")
        self._repositories = tuple(
            FilePolicyRepository(path, database_url if index == 0 else None)
            for index, path in enumerate(policy_dirs)
        )
        self._cache: dict[str, DetectionPolicy] = {}

    def resolve(self, version: str) -> DetectionPolicy:
        if version in self._cache:
            return self._cache[version]
        matches: list[DetectionPolicy] = []
        for repository in self._repositories:
            try:
                matches.append(repository.resolve(version))
            except PolicyNotFoundError:
                continue
        if not matches:
            raise PolicyNotFoundError(version)
        if len(matches) != 1:
            raise ValueError(
                f"Policy version {version!r} exists in multiple policy directories"
            )
        policy = matches[0]
        self._cache[version] = policy
        return policy

    def active_version(self) -> str | None:
        return self._repositories[0].active_version()

    async def initialize(self) -> None:
        await self._repositories[0].initialize()

    async def list_versions(self) -> list[dict]:
        return await self._repositories[0].list_versions()

    async def save_draft(self, policy: DetectionPolicy, source: str) -> bool:
        return await self._repositories[0].save_draft(policy, source)

    async def publish(self, policy: DetectionPolicy, source: str) -> bool:
        published = await self._repositories[0].publish(policy, source)
        if published:
            self._cache.pop(policy.version, None)
        return published

    async def activate(self, version: str) -> bool:
        activated = await self._repositories[0].activate(version)
        if activated:
            self._cache.pop(version, None)
        return activated
