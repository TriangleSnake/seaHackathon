import unittest
from unittest.mock import AsyncMock, patch

from app.main import patrol_run
from app.models import PatrolPolicyRef, PatrolRequest, PatrolResult, PatrolScope


class PatrolRunHandoffGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_association_first_skips_only_legacy_direct_handoff(self):
        request = PatrolRequest(
            run_id="demo-run",
            mode="manual",
            strategy="explore",
            scope=PatrolScope(),
        )
        result = PatrolResult(
            run_id="demo-run",
            strategy="explore",
            policy_ref=PatrolPolicyRef(id="patrol-explore", version="test"),
            discoveries=[],
            evidence=[],
        )
        with (
            patch("app.main.load_active_policy", return_value=object()),
            patch("app.main.run_patrol", AsyncMock(return_value=result)),
            patch("app.main.handoff_to_investigation", AsyncMock()) as handoff,
        ):
            returned = await patrol_run(request, "association-first")
            self.assertEqual(returned, result)
            handoff.assert_not_awaited()

            await patrol_run(request, None)
            handoff.assert_awaited_once_with(result)


if __name__ == "__main__":
    unittest.main()
