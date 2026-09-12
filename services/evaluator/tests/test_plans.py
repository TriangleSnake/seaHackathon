from app.models import PolicyType
from app.plans import RegisteredCandidateEvaluationPlanResolver


class Ref:
    def __init__(self, policy_type, version):
        self.policy_type = policy_type
        self.version = version


class Base:
    version = "DV-001"
    policies = (Ref("detection", "baseline-v1"), Ref("scoring", "SP-001"))


class Candidate:
    target_policy = "detection"
    policy_ref = Ref("detection", "DP-CAND-001")


class Registry:
    def resolve(self, candidate_id):
        assert candidate_id == "candidate-001"
        return Candidate()


class Versions:
    candidate_registry = Registry()

    def read_base(self, version):
        assert version == "DV-001"
        return Base()


def test_registered_candidate_plan_resolves_exact_policy_refs() -> None:
    plan = RegisteredCandidateEvaluationPlanResolver(Versions()).resolve(
        "candidate-001", "DV-001"
    )

    assert plan.policy_type is PolicyType.DETECTION
    assert plan.baseline_policy_ref == "baseline-v1"
    assert plan.candidate_policy_ref == "DP-CAND-001"
