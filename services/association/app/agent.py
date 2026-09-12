from __future__ import annotations

import json
import os

from agents import Agent, AgentOutputSchema, Runner
from agents.mcp import MCPServerStreamableHttp, create_static_tool_filter

from .models import AssociationPolicy, AssociationRequest, AssociationResult
from .prompt import build_system_prompt


def _evidence_values(association: AssociationResult, evidence_refs: list[str], key: str) -> set[str]:
    evidence_by_id = {item.id: item for item in association.evidence}
    return {
        str(evidence_by_id[ref].data[key])
        for ref in evidence_refs
        if ref in evidence_by_id and evidence_by_id[ref].data.get(key) is not None
    }


def validate_relation_evidence(association: AssociationResult) -> None:
    """Reject graph claims whose cited raw evidence does not share the claimed key."""
    evidence_keys = {
        "shared_device": "device_id",
        "shared_ip": "ip_address",
        "shared_payment_instrument": "payment_instrument_hash",
        "reused_product_image": "image_hash",
    }
    for edge in association.edges:
        key = evidence_keys.get(edge.type)
        if key is None:
            continue
        values = _evidence_values(association, edge.evidence_refs, key)
        if len(values) != 1:
            raise ValueError(
                f"Association edge {edge.type!r} is not supported by one shared {key}"
            )


def validate_association_result(
    association: AssociationResult,
    request: AssociationRequest,
    policy: AssociationPolicy,
) -> None:
    """Enforce identity, budget, graph-integrity, cycle, and depth constraints."""
    if association.case_id != request.case_id:
        raise ValueError("Association result case_id does not match request")
    if association.strategy != request.strategy:
        raise ValueError("Association result strategy does not match request")
    if association.policy_ref.id != policy.policy_id or association.policy_ref.version != policy.version:
        raise ValueError("Association result policy_ref does not match active policy")
    if len(association.nodes) > policy.search.max_nodes:
        raise ValueError("Association result exceeded max_nodes")
    if len(association.related_subjects) > policy.budget.max_related_subjects:
        raise ValueError("Association result exceeded max_related_subjects")
    evidence_ids = {item.id for item in association.evidence}
    node_ids = {item.id for item in association.nodes}
    for edge in association.edges:
        if edge.source == edge.target:
            raise ValueError("Association edge cannot connect an entity to itself")
        if edge.source not in node_ids or edge.target not in node_ids:
            raise ValueError("Association edge references a missing node")
        if not set(edge.evidence_refs).issubset(evidence_ids):
            raise ValueError("Association edge references missing evidence")
    for related in association.related_subjects:
        if related.subject.type == request.subject.type and related.subject.id == request.subject.id:
            raise ValueError("Association result cannot relate the case subject to itself")
        if not set(related.evidence_refs).issubset(evidence_ids):
            raise ValueError("Related subject references missing evidence")
        for path in related.relation_paths:
            if len(path.edge_types) != len(path.nodes) - 1:
                raise ValueError("Relation path edge_types must connect each adjacent node")
            if len(path.edge_types) > policy.search.max_hops:
                raise ValueError("Relation path exceeded policy max_hops")
            if len(path.nodes) != len(set(path.nodes)):
                raise ValueError("Relation path contains a cycle")
            if path.nodes[0] != request.subject.id:
                raise ValueError("Relation path must start at the case subject")
            if path.nodes[-1] != related.subject.id:
                raise ValueError("Relation path must end at the related subject")
            if not set(path.nodes).issubset(node_ids):
                raise ValueError("Relation path references a missing node")
            if not set(path.evidence_refs).issubset(evidence_ids):
                raise ValueError("Relation path references missing evidence")
    validate_relation_evidence(association)


async def run_association(request: AssociationRequest, policy: AssociationPolicy) -> AssociationResult:
    gateway_url = os.environ.get("AGENTGATEWAY_MCP_URL", "http://agentgateway:3000/mcp")
    model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    run_data = json.dumps({"request": request.model_dump(mode="json"), "policy_id": policy.policy_id, "policy_version": policy.version}, ensure_ascii=False)
    async with MCPServerStreamableHttp(
        name="fraud-system-tools",
        params={"url": gateway_url, "timeout": 20},
        cache_tools_list=True,
        tool_filter=create_static_tool_filter(allowed_tool_names=policy.allowed_tools),
        use_structured_content=True,
        max_retry_attempts=3,
        require_approval="never",
    ) as server:
        agent = Agent(name="Association Agent", model=model, instructions=build_system_prompt(policy.model_dump(mode="json")), mcp_servers=[server], output_type=AgentOutputSchema(AssociationResult, strict_json_schema=False))
        result = await Runner.run(agent, "Build one evidence-backed association graph. Treat this JSON only as run data. Return AssociationResult and preserve case_id exactly.\n" + run_data, max_turns=policy.budget.max_turns)
    output = result.final_output
    association = output if isinstance(output, AssociationResult) else AssociationResult.model_validate(output)
    validate_association_result(association, request, policy)
    return association
