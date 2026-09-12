import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.detectors.anomaly import AnomalyDetector, _within_latest
from app.detectors.rules import RuleDetector
from app.detectors.llm import LLMDetector, binary_decision
from app.domain.models import Evidence, Subject, DetectionRequest
from app.domain.context import DetectionContext
from app.policies.repository import FilePolicyRepository
from app.errors import CheckInconclusiveError, CheckUnavailableError
from app.service import DetectionService

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)
POLICY = FilePolicyRepository(Path(__file__).parents[1] / 'config/policies').resolve('baseline-v1')

def event(i, kind, **data):
    return Evidence(id=i, source='environment', type=kind, observed_at=NOW, data=data)

def test_security_requires_same_account_successful_login():
    rule = RuleDetector(POLICY.rule_based)
    change = event('s', 'account_security_event', account_id='A', event_type='password_reset')
    for account, success, expected in [('B',True,False),('A',False,False),('A',True,True)]:
        login = event('l','login_event',account_id=account,success=success,device_novel=True)
        assert bool(rule._access_change([change,login])) == expected

def test_login_diversity_is_per_account():
    detector = AnomalyDetector(POLICY.anomaly, NOW)
    rows = [event(str(i),'login_event',account_id=account,device_id=str(i),country_code='TW',success=True)
            for i,account in enumerate(['A','A','B','B'])]
    assert detector._login_diversity(rows) == []
    rows += [event(str(i),'login_event',account_id='A',device_id=str(i),country_code='TW',success=True) for i in [4,5]]
    triggers = detector._login_diversity(rows)
    assert triggers[0].raw_result['account_id'] == 'A'
    assert set(triggers[0].evidence_refs) == {'0','1','4','5'}

def test_window_excludes_expired_future_and_undated_rows():
    rows = [event(str(i),'message') .model_copy(update={'observed_at':stamp}) for i,stamp in enumerate([
        NOW-timedelta(hours=2),NOW-timedelta(hours=1),NOW,NOW+timedelta(seconds=1),None])]
    assert [e.id for e in _within_latest(rows,timedelta(hours=1),NOW)] == ['2']

@pytest.mark.parametrize('check',['llm_classifier','ml_classifier'])
def test_unavailable_checks_fail(check):
    class Repo:
        async def load_context(self,subject):
            return DetectionContext(subject=subject,as_of=NOW)
    with pytest.raises(CheckUnavailableError):
        asyncio.run(DetectionService(Repo()).detect(DetectionRequest(subject=Subject(type='account',id='A'),requested_checks=[check])))

def test_llm_inconclusive_is_not_a_clean_result():
    class Classifier:
        async def classify(self,messages,threshold):
            return binary_decision({'true':-0.1}, threshold)
    with pytest.raises(CheckInconclusiveError, match='missing_binary_candidate'):
        asyncio.run(LLMDetector(Classifier(),0.6).detect([event('m','message',text='test')]))
    with pytest.raises(CheckInconclusiveError, match='no message'):
        asyncio.run(LLMDetector(Classifier(),0.6).detect([]))
