from __future__ import annotations
import json, os
from typing import Any
import psycopg
from psycopg.rows import dict_row

DATABASE_URL=os.environ.get("DATABASE_URL","postgresql://fraud:fraud_dev_password@postgres:5432/fraud_intelligence")

def get_active(agent: str, strategy: str) -> dict[str, Any] | None:
    try:
        with psycopg.connect(DATABASE_URL,row_factory=dict_row) as conn:
            row=conn.execute("SELECT document FROM agent_policies WHERE agent=%s AND strategy=%s AND active",(agent,strategy)).fetchone()
            return row["document"] if row else None
    except psycopg.Error: return None

async def initialize_policy_storage() -> None:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('agent-control-schema'))")
        await conn.execute("""CREATE TABLE IF NOT EXISTS agent_policies(agent TEXT NOT NULL,strategy TEXT NOT NULL,version TEXT NOT NULL,document JSONB NOT NULL,active BOOLEAN NOT NULL DEFAULT false,source TEXT NOT NULL DEFAULT 'human',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(agent,strategy,version)); CREATE UNIQUE INDEX IF NOT EXISTS agent_policies_one_active_idx ON agent_policies(agent,strategy) WHERE active;""")

async def list_policies(agent: str,strategy: str|None=None)->list[dict[str,Any]]:
    query="SELECT agent,strategy,version,document,active,source,created_at FROM agent_policies WHERE agent=%s"; params:(tuple[Any,...])=(agent,)
    if strategy: query+=" AND strategy=%s"; params+=(strategy,)
    query+=" ORDER BY created_at DESC"
    async with await psycopg.AsyncConnection.connect(DATABASE_URL,row_factory=dict_row) as conn: return list(await (await conn.execute(query,params)).fetchall())

async def publish(agent:str,strategy:str,version:str,document:dict[str,Any],source:str)->bool:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.transaction():
            existing=await (await conn.execute("SELECT document FROM agent_policies WHERE agent=%s AND strategy=%s AND version=%s",(agent,strategy,version))).fetchone()
            if existing and existing[0]!=document:return False
            await conn.execute("UPDATE agent_policies SET active=false WHERE agent=%s AND strategy=%s",(agent,strategy))
            if existing: await conn.execute("UPDATE agent_policies SET active=true WHERE agent=%s AND strategy=%s AND version=%s",(agent,strategy,version))
            else: await conn.execute("INSERT INTO agent_policies(agent,strategy,version,document,active,source) VALUES(%s,%s,%s,%s::jsonb,true,%s)",(agent,strategy,version,json.dumps(document),source))
            return True

async def save_draft(agent:str,strategy:str,version:str,document:dict[str,Any],source:str)->bool:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        result=await conn.execute("INSERT INTO agent_policies(agent,strategy,version,document,active,source) VALUES(%s,%s,%s,%s::jsonb,false,%s) ON CONFLICT(agent,strategy,version) DO NOTHING",(agent,strategy,version,json.dumps(document),source)); return result.rowcount==1

async def activate(agent:str,strategy:str,version:str)->bool:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.transaction():
            exists=await (await conn.execute("SELECT 1 FROM agent_policies WHERE agent=%s AND strategy=%s AND version=%s",(agent,strategy,version))).fetchone()
            if not exists:return False
            await conn.execute("UPDATE agent_policies SET active=false WHERE agent=%s AND strategy=%s",(agent,strategy))
            await conn.execute("UPDATE agent_policies SET active=true WHERE agent=%s AND strategy=%s AND version=%s",(agent,strategy,version)); return True
