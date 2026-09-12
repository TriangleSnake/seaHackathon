from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app import control


class ControlRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_detection_hit_enqueues_investigation_child(self) -> None:
        job = {
            "job_id": "job-detect",
            "agent": "detection",
            "trigger_type": "event",
            "trigger_ref": "message.created:MSG-1",
            "event_type": "message.created",
            "subject": {"type": "message", "id": "MSG-1"},
            "payload": {"auto_investigate": True, "routing": {"association_depth": 0}},
        }
        result = {
            "detection_id": "DET-1",
            "subject": job["subject"],
            "detected": True,
            "triggers": [],
            "evidence": [],
        }
        with (
            patch.object(control.storage, "claim_job", AsyncMock(return_value=job)),
            patch.object(control.clients, "run_detection", AsyncMock(return_value=result)),
            patch.object(control.storage, "complete_job", AsyncMock()) as complete,
            patch.object(control.storage, "enqueue_child_job", AsyncMock()) as enqueue,
        ):
            await control.work_once()

        complete.assert_awaited_once_with("job-detect", result)
        self.assertEqual(enqueue.await_args.args[1], "investigation")
        self.assertEqual(enqueue.await_args.args[3]["detection_result"], result)

    async def test_patrol_discovery_reconciles_to_detection_child(self) -> None:
        job = {
            "job_id": "job-patrol",
            "agent": "patrol",
            "trigger_type": "schedule",
            "trigger_ref": "patrol-default:1",
            "event_type": None,
            "remote_status_url": "/patrol/jobs/remote-1",
        }
        remote = {
            "status": "completed",
            "result": {
                "run_id": "run-1",
                "discoveries": [
                    {"subject": {"type": "account", "id": "ACC-1"}, "reason": "burst"}
                ],
            },
        }
        with (
            patch.object(control.storage, "list_remote_jobs", AsyncMock(return_value=[job])),
            patch.object(control.clients, "patrol_status", AsyncMock(return_value=remote)),
            patch.object(control.storage, "complete_job", AsyncMock()),
            patch.object(control.storage, "enqueue_child_job", AsyncMock()) as enqueue,
        ):
            await control.reconcile_once()

        self.assertEqual(enqueue.await_args.args[1], "detection")
        self.assertEqual(enqueue.await_args.args[2], {"type": "account", "id": "ACC-1"})
        self.assertTrue(enqueue.await_args.args[3]["auto_investigate"])


if __name__ == "__main__":
    unittest.main()
