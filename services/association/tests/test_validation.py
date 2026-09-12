import unittest

from app.agent import validate_relation_evidence
from app.models import AssociationResult


def result_with_hashes(first: str, second: str) -> AssociationResult:
    return AssociationResult.model_validate({
        "case_id": "case-test", "strategy": "focused",
        "policy_ref": {"id": "association-focused", "version": "test"},
        "nodes": [{"id": "A", "type": "account"}, {"id": "B", "type": "account"}],
        "edges": [{"source": "A", "target": "B", "type": "shared_payment_instrument",
                   "relationship": "observed", "confidence": 1, "evidence_refs": ["E1", "E2"]}],
        "related_subjects": [],
        "evidence": [
            {"id": "E1", "source": "environment", "type": "payment", "data": {"payment_instrument_hash": first}},
            {"id": "E2", "source": "environment", "type": "payment", "data": {"payment_instrument_hash": second}},
        ],
    })


class RelationEvidenceTests(unittest.TestCase):
    def test_accepts_one_shared_value(self):
        validate_relation_evidence(result_with_hashes("same", "same"))

    def test_rejects_different_values(self):
        with self.assertRaisesRegex(ValueError, "not supported"):
            validate_relation_evidence(result_with_hashes("one", "two"))


if __name__ == "__main__":
    unittest.main()
