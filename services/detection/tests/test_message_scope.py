import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.domain.context import DetectionContext
from app.domain.models import DetectionRequest, Evidence, Subject
from app.detectors.llm import LLMClassification
from app.repository import PostgresDetectionRepository
from app.service import DetectionService

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def message(identifier, text, sender):
    return Evidence(id=identifier, type='message', source='environment', observed_at=NOW,
                    data={'text': text, 'sender_account_id': sender, 'conversation_id': 'C'})


def test_repository_message_scope_never_loads_account_risk():
    class Repository(PostgresDetectionRepository):
        async def _resolve_accounts(self, subject):
            return ['sender', 'recipient']

        async def _load_messages(self, subject, accounts):
            return [message(subject.id, '我不會私下付款', 'sender')]

        async def _load_reports(self, subject, accounts):
            return []

        async def _load_message_background(self, message_id):
            return [message('background', '先匯保留金', 'recipient')]

        async def _load_account_access(self, accounts):
            raise AssertionError('Account-wide data must not enter message scope')

    async def run():
        repo = Repository.__new__(Repository)
        subject = Subject(type='message', id='target')
        context = await repo._load_context(subject, NOW)
        class FixedRepository:
            async def load_context(self, subject):
                return context
        result = await DetectionService(FixedRepository()).detect(DetectionRequest(subject=subject))
        assert result.detected is False
        assert [e.id for e in context.evidence] == ['target']
        assert [e.id for e in context.conversation_context] == ['background']
    asyncio.run(run())


def test_llm_target_background_and_evidence_are_explicit():
    subject = Subject(type='message', id='target')
    target = message('target', '請到驗證頁重新開通', 'sender')
    background = message('background', '請問怎麼付款', 'recipient').model_copy(
        update={'observed_at': NOW - timedelta(minutes=5)})
    class Repository:
        async def load_context(self, subject):
            return DetectionContext(subject, evidence=[target], conversation_context=[background])
    captured = {}
    class Classifier:
        async def classify(self, messages, threshold):
            payload = json.loads(messages[0])
            captured.update(payload)
            assert payload['target_message']['id'] == 'target'
            assert payload['target_message']['sender_account_id'] == 'sender'
            assert payload['background_messages'][0]['sender_account_id'] == 'recipient'
            return LLMClassification(True, {'decision': 'trigger'})
    result = asyncio.run(DetectionService(Repository(), Classifier()).detect(
        DetectionRequest(subject=subject, requested_checks=['llm_classifier'])))
    assert captured['target_message']['observed_at'] == '2026-09-10T00:00:00+00:00'
    assert captured['background_messages'][0]['observed_at'] == '2026-09-09T23:55:00+00:00'
    assert result.triggers[0].raw_result['target_message_id'] == 'target'
    assert result.triggers[0].evidence_refs == ['target', 'background']
    assert {e.id for e in result.evidence} == {'target', 'background'}
