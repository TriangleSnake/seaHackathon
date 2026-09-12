import unittest

from app.agent import validate_association_result, validate_relation_evidence
from app.models import AssociationPolicy, AssociationRequest, AssociationResult


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


class GraphSafetyTests(unittest.TestCase):
    def setUp(self):
        self.request = AssociationRequest.model_validate({
            "case_id": "case-test", "subject": {"type": "account", "id": "A"},
            "strategy": "focused",
        })
        self.policy = AssociationPolicy.model_validate({
            "policy_id": "association-focused", "version": "test", "strategy": "focused",
            "objective": "test", "allowed_tools": [], "search": {"max_hops": 1},
        })

    def result(self, related_id="B", path_nodes=None, edge_source="A", edge_target="B"):
        path_nodes = path_nodes or ["A", "B"]
        return AssociationResult.model_validate({
            "case_id": "case-test", "strategy": "focused",
            "policy_ref": {"id": "association-focused", "version": "test"},
            "nodes": [{"id": item, "type": "account"} for item in dict.fromkeys(path_nodes + [edge_source, edge_target])],
            "edges": [{"source": edge_source, "target": edge_target, "type": "observed_link",
                       "relationship": "observed", "confidence": 1, "evidence_refs": ["E1"]}],
            "related_subjects": [{"subject": {"type": "account", "id": related_id},
                "association_score": 0.5, "reason": "test",
                "relation_paths": [{"nodes": path_nodes, "edge_types": ["link"] * (len(path_nodes) - 1), "evidence_refs": ["E1"]}],
                "evidence_refs": ["E1"]}],
            "evidence": [{"id": "E1", "source": "environment", "type": "test", "data": {}}],
        })

    def test_accepts_bounded_path(self):
        validate_association_result(self.result(), self.request, self.policy)

    def test_accepts_canonical_graph_ids_for_raw_subject_ids(self):
        result = self.result(
            related_id="B",
            path_nodes=["account:A", "account:B"],
            edge_source="account:A",
            edge_target="account:B",
        )
        validate_association_result(result, self.request, self.policy)

    def test_rejects_canonical_self_related_subject(self):
        with self.assertRaisesRegex(ValueError, "case subject to itself"):
            validate_association_result(
                self.result(related_id="account:A", path_nodes=["A", "B"]),
                self.request,
                self.policy,
            )

    def test_rejects_self_related_subject(self):
        with self.assertRaisesRegex(ValueError, "case subject to itself"):
            validate_association_result(self.result(related_id="A", path_nodes=["A", "B"]), self.request, self.policy)

    def test_rejects_cycle(self):
        with self.assertRaisesRegex(ValueError, "max_hops|cycle"):
            validate_association_result(self.result(path_nodes=["A", "B", "A"]), self.request, self.policy)

    def test_rejects_path_beyond_max_hops(self):
        with self.assertRaisesRegex(ValueError, "max_hops"):
            validate_association_result(self.result(related_id="C", path_nodes=["A", "B", "C"]), self.request, self.policy)

    def test_rejects_self_edge(self):
        with self.assertRaisesRegex(ValueError, "itself"):
            validate_association_result(self.result(edge_target="A"), self.request, self.policy)


if __name__ == "__main__":
    unittest.main()
