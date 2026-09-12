from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = Path(__file__).resolve().parent
for path in (REPOSITORY_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from codex_builder.runtime import CodeBuilderSettings, RealCodexCodeBuilder
from services.evolution.app.capabilities import DetectionPolicyCapabilityAdapter
from services.evolution.app.code_builder import CodexCandidateBuilder
from services.evolution.app.domain import PolicyChangeProposal, PolicyType


INTEGRATION_BASE = "96ab1e05c8f8d9e721816cabdf92d6fdde01e13c"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the real isolated Codex builder for the seller-payment hero case"
    )
    parser.add_argument("--build-id", default="build-real-codex-hero-001")
    parser.add_argument("--source-repository", default=str(REPOSITORY_ROOT))
    parser.add_argument(
        "--candidate-root", default="/private/tmp/member4-real-codex-candidates"
    )
    parser.add_argument(
        "--artifact-root", default="/private/tmp/member4-real-codex-artifacts"
    )
    parser.add_argument("--codex-executable", default="codex")
    arguments = parser.parse_args()

    acceptance = (
        SERVICE_ROOT
        / "tests"
        / "acceptance"
        / "seller_conditional_payment_acceptance.py"
    )
    settings = CodeBuilderSettings.for_detection(
        source_repository=arguments.source_repository,
        base_commit=INTEGRATION_BASE,
        acceptance_test=acceptance,
        candidate_root=arguments.candidate_root,
        artifact_root=arguments.artifact_root,
        codex_executable=arguments.codex_executable,
    )
    proposal = PolicyChangeProposal(
        proposal_id="proposal-seller-conditional-payment",
        target_policy=PolicyType.DETECTION,
        base_defense_version="DV-001",
        base_policy_version="baseline-v1",
        objective="Detect seller conditional-payment inducement",
        requested_behavior=(
            "Detect seller messages that condition payment on an extreme discount "
            "or urgent incentive, requiring sender role, payment-action intent, "
            "and inducement intent in the same message"
        ),
        required_signals=(
            "sender.marketplace_role",
            "message.payment_action",
            "message.extreme_discount_or_urgency_inducement",
        ),
        known_risks=("legitimate seller promotion language",),
        provenance={"source": "deterministic-code-pipeline-proof"},
    )
    directive = DetectionPolicyCapabilityAdapter().resolve(proposal)
    builder = CodexCandidateBuilder(RealCodexCodeBuilder(settings))
    outcome = builder.build(
        {
            "build_id": arguments.build_id,
            "pattern_spec": {
                "pattern_id": "pattern-seller-conditional-payment",
                "name": "Seller conditional-payment inducement",
            },
            "base_defense_version": {"version": "DV-001"},
            "target_policies": ["detection"],
        },
        proposal,
        directive,
    )
    payload = {
        "implementation_mode": directive.kind.value,
        "candidate_result": dict(outcome.candidate_result),
        "candidate_policy_ref": (
            outcome.candidate_policy.policy_ref.version
            if outcome.candidate_policy
            else None
        ),
        "success": outcome.success,
        "error": outcome.error,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if outcome.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
