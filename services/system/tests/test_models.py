from datetime import datetime, timezone
import unittest

from pydantic import ValidationError

from app.models import AgentModelConfig, SystemSchedule
from app.clients import _runtime_headers
from app.routing import choose_patrol_strategy, event_idempotency_key


class ControlPlaneTests(unittest.TestCase):
    def test_weighted_patrol_strategy_is_deterministic(self) -> None:
        weights = {"exploit": 4, "explore": 1}
        self.assertEqual([choose_patrol_strategy(i, weights) for i in range(10)], [
            "exploit", "exploit", "exploit", "exploit", "explore",
            "exploit", "exploit", "exploit", "exploit", "explore",
        ])

    def test_schedule_rejects_empty_strategy_mix(self) -> None:
        with self.assertRaises(ValidationError):
            SystemSchedule(schedule_id="patrol", config={
                "strategy_weights": {"exploit": 0, "explore": 0}, "scope": {}
            })

    def test_event_key_collapses_same_subject_in_cooldown_bucket(self) -> None:
        at = datetime(2026, 9, 12, 1, 0, 5, tzinfo=timezone.utc)
        first = event_idempotency_key("p", "v1", "message:1", "account", "A", at, 30)
        second = event_idempotency_key("p", "v1", "message:2", "account", "A", at.replace(second=20), 30)
        self.assertEqual(first, second)

    def test_event_key_keeps_distinct_events_without_cooldown(self) -> None:
        at = datetime(2026, 9, 12, tzinfo=timezone.utc)
        self.assertNotEqual(
            event_idempotency_key("p", "v1", "message:1", "message", "1", at, 0),
            event_idempotency_key("p", "v1", "message:2", "message", "2", at, 0),
        )

    def test_agent_model_config_rejects_unknown_component(self) -> None:
        with self.assertRaises(ValidationError):
            AgentModelConfig(
                component="unknown",
                model="gpt-5-mini",
                allowed_models=["gpt-5-mini"],
            )

    def test_runtime_headers_are_scoped_to_dispatched_job(self) -> None:
        self.assertEqual(
            _runtime_headers({"payload": {"_runtime": {
                "model": "gpt-5-mini", "reasoning_effort": "medium"
            }}}),
            {
                "X-Agent-Model": "gpt-5-mini",
                "X-Agent-Reasoning-Effort": "medium",
            },
        )

    def test_agent_model_config_enforces_server_allowlist(self) -> None:
        with self.assertRaises(ValidationError):
            AgentModelConfig(component="patrol", model="untrusted-model")


if __name__ == "__main__":
    unittest.main()
