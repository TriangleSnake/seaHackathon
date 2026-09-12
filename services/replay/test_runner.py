import os
import unittest
from datetime import datetime, timezone

import httpx
import psycopg
from runner import DDL, prepare, dispatch


class ReplayTests(unittest.TestCase):
    def test_boundaries_retry_policy_and_clock_drift(self):
        with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as db:
            db.execute(DDL)
            db.execute('TRUNCATE replay.jobs, replay.batches RESTART IDENTITY')
            start = datetime(2026, 9, 1, tzinfo=timezone.utc)
            for suffix, stamp in [('start', '2026-09-01T00:00:00Z'), ('end', '2026-09-02T00:00:00Z'), ('later', '2026-09-03T00:00:00Z')]:
                db.execute("INSERT INTO accounts(id,account_type,country_code,created_at,status) VALUES(%s,'buyer','TW',%s,'active') ON CONFLICT DO NOTHING", ('replay-test-'+suffix, stamp))
            db.execute('SELECT set_simulation_time(%s)', (start,))
            batch = prepare(db, 86400, 'baseline-v1')
            self.assertEqual(prepare(db, 1, 'candidate-v1'), batch)
            count, = db.execute('SELECT count(*) FROM replay.jobs WHERE batch_id=%s', (batch[0],)).fetchone()
            self.assertGreater(count, 0)
            ids = {row[0] for row in db.execute('SELECT subject_id FROM replay.jobs WHERE batch_id=%s', (batch[0],))}
            self.assertIn('replay-test-end', ids)
            self.assertNotIn('replay-test-start', ids)
            self.assertNotIn('replay-test-later', ids)
            calls = []
            def respond(request):
                import json
                body = json.loads(request.content)
                calls.append(body)
                return httpx.Response(200, headers={'X-Detection-Policy-Version': 'baseline-v1'}, json={
                    'subject': body['subject'], 'detected': False, 'triggers': []})
            with httpx.Client(base_url='http://test', transport=httpx.MockTransport(respond)) as client:
                dispatch(db, client, *batch)
                dispatch(db, client, *batch)
            self.assertEqual(len(calls), count)
            self.assertTrue(all(x['policy_ref']['version']=='baseline-v1' for x in calls))
            next_batch = prepare(db, 86400, 'candidate-v1')
            with httpx.Client(base_url='http://test', transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
                with self.assertRaises(httpx.HTTPStatusError):
                    dispatch(db, client, *next_batch)
            self.assertEqual(prepare(db, 1, 'baseline-v1'), next_batch)
            db.execute("SELECT advance_simulation_time(interval '1 second')")
            with self.assertRaises(RuntimeError):
                prepare(db, 1, 'baseline-v1')


if __name__ == '__main__':
    unittest.main()
