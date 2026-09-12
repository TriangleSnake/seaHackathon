import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.jobs import PatrolJobManager
from app.models import PatrolPolicy, PatrolRequest, PatrolResult


class PatrolJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_completes_without_handoff_when_no_discoveries(self):
        policy = PatrolPolicy.model_validate({"policy_id":"p","version":"1","strategy":"exploit","objective":"test","allowed_tools":[]})
        request = PatrolRequest.model_validate({"run_id":"r","mode":"manual","strategy":"exploit","scope":{"subject_types":[]}})
        result = PatrolResult.model_validate({"run_id":"r","strategy":"exploit","policy_ref":{"id":"p","version":"1"},"discoveries":[],"evidence":[]})
        memory = {}
        async def put(job_id, request_data, state): memory[job_id] = state
        async def get(job_id): return memory.get(job_id)
        with patch("app.jobs.put_job", side_effect=put), patch("app.jobs.load_job", side_effect=get), patch("app.jobs.load_jobs", AsyncMock(return_value=[])), patch("app.jobs.run_patrol", AsyncMock(return_value=result)):
            manager = PatrolJobManager(); accepted = await manager.submit(request, policy); await asyncio.sleep(0.02)
            state = await manager.get(accepted.job_id)
            self.assertEqual(state.status, "completed"); self.assertEqual(state.handoff_status, "not_required")


if __name__ == "__main__": unittest.main()
