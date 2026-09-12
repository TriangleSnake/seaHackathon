"""Fixture expectations remain outside marketplace tables."""
import asyncio
import os
from datetime import datetime

import psycopg
import pytest
from app.domain.models import DetectionRequest, Subject
from app.repository import PostgresDetectionRepository
from app.service import DetectionService

DATABASE_URL = os.environ.get('DETECTION_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='integration DB not configured')


def test_anomaly_seed_boundaries_and_ordinary_controls():
    async def run():
        repo = PostgresDetectionRepository(DATABASE_URL)
        service = DetectionService(repo)
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as db:
            previous = (await (await db.execute('SELECT simulation_time FROM simulation_state')).fetchone())[0]
            try:
                # Threshold minus one, threshold, threshold plus one.
                groups = [
                    ('2026-09-06T10:30:00+08:00','ANOMALY-CHAT-001',[1,2,3]),
                    ('2026-09-06T11:30:00+08:00','ANOMALY-LISTING-001',[4,8,12]),
                    ('2026-09-06T15:00:00+08:00','ANOMALY-ACCESS-001',[5,6,7]),
                    ('2026-09-06T15:00:00+08:00','ANOMALY-ACCESS-001',[9,10,11]),
                    ('2026-09-07T13:00:00+08:00','ANOMALY-DISPUTE-001',[14,15,17]),
                ]
                for stamp, rule, accounts in groups:
                    await db.execute('SELECT set_simulation_time(%s)',(stamp,))
                    for number, expected in zip(accounts,[False,True,True]):
                        result = await service.detect(DetectionRequest(subject=Subject(type='account',id=f'ACC-{number:04d}'),requested_checks=['anomaly']))
                        assert (rule in {t.rule_id for t in result.triggers}) == expected, (stamp,number,result)
                for stamp, subject, rule, expected in [
                    ('2026-09-06T15:00:00+08:00',Subject(type='account',id='ACC-0013'),'ANOMALY-ACCESS-001',False),
                    ('2026-09-06T12:10:00+08:00',Subject(type='transaction',id='TXN-2001'),'ANOMALY-PAYMENT-001',False),
                    ('2026-09-04T10:08:00+08:00',Subject(type='transaction',id='TXN-0091'),'ANOMALY-PAYMENT-001',True),
                    ('2026-09-04T11:08:00+08:00',Subject(type='transaction',id='TXN-0091'),'ANOMALY-PAYMENT-001',False),
                ]:
                    await db.execute('SELECT set_simulation_time(%s)',(stamp,))
                    result = await service.detect(DetectionRequest(subject=subject,requested_checks=['anomaly']))
                    assert (rule in {t.rule_id for t in result.triggers}) == expected
            finally:
                await db.execute('SELECT set_simulation_time(%s)',(previous,))
                await repo.close()
    asyncio.run(run())


def test_detection_reads_effective_product_price():
    async def run():
        repo = PostgresDetectionRepository(DATABASE_URL)
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as db:
            previous = (await (await db.execute('SELECT simulation_time FROM simulation_state')).fetchone())[0]
            try:
                for stamp, expected in [('2026-09-04T09:09:59+08:00',3196),('2026-09-04T09:10:00+08:00',99)]:
                    await db.execute('SELECT set_simulation_time(%s)',(stamp,))
                    context = await repo.load_context(Subject(type='product',id='PROD-0081'))
                    price = next(e.data['price'] for e in context.evidence if e.id=='PROD-0081')
                    assert float(price)==expected
                    assert context.as_of==datetime.fromisoformat(stamp)
            finally:
                await db.execute('SELECT set_simulation_time(%s)',(previous,))
                await repo.close()
    asyncio.run(run())
