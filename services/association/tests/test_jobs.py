import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.jobs import AssociationJobManager
from app.models import AssociationPolicy, AssociationRequest, AssociationResult


class AssociationJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_is_idempotent_and_persisted(self):
        policy = AssociationPolicy.model_validate({"policy_id":"p","version":"1","strategy":"focused","objective":"test","allowed_tools":[]})
        request = AssociationRequest.model_validate({"case_id":"c","subject":{"type":"account","id":"A"},"strategy":"focused"})
        result = AssociationResult.model_validate({"case_id":"c","strategy":"focused","policy_ref":{"id":"p","version":"1"},"nodes":[],"edges":[],"related_subjects":[],"evidence":[]})
        memory = {}
        async def put(job_id, request_data, state): memory[job_id] = state
        async def get(job_id): return memory.get(job_id)
        with patch("app.jobs.put_job", side_effect=put), patch("app.jobs.load_job", side_effect=get), patch("app.jobs.load_jobs", AsyncMock(return_value=[])), patch("app.jobs.run_association", AsyncMock(return_value=result)):
            manager = AssociationJobManager(); first = await manager.submit(request, policy); second = await manager.submit(request, policy); await asyncio.sleep(0.02)
            state = await manager.get(first.job_id)
            self.assertEqual(first.job_id, second.job_id); self.assertEqual(state.status, "completed")


if __name__ == "__main__": unittest.main()
