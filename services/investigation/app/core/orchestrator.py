"""Budgeted, evidence-first dynamic multi-agent orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.base import DomainAgent
from app.domain.models import (
    AgentInvocation,
    AgentUsage,
    Evidence,
    Finding,
    InvestigationRequest,
    InvestigationResult,
    ScoreboardUsage,
    ScoreboardState,
    SpecialistAgentResult,
    StopReason,
    Subject,
)
from app.evidence.ledger import EvidenceLedger
from app.gateways.mcp import MCPGatewayClient
from app.policies.repository import FilePolicyRepository
from app.scoring.engine import confidence_for, verdict_for
from app.scoring.weighted import AgentScoreAggregator, combine_agent_scores


class InvestigationOrchestrator:
    def __init__(
        self,
        gateway: MCPGatewayClient,
        policy_repository: FilePolicyRepository,
        agents: list[DomainAgent],
        score_aggregator: Optional[AgentScoreAggregator] = None,
    ) -> None:
        self._gateway = gateway
        self._policies = policy_repository
        self._agents = agents
        self._score_aggregator = score_aggregator or AgentScoreAggregator()

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(agent.name for agent in self._agents)

    async def investigate(
        self,
        request: InvestigationRequest,
        request_id: str,
        traceparent: Optional[str] = None,
    ) -> InvestigationResult:
        config = self._policies.resolve(request.scoreboard_config_ref)
        ledger = EvidenceLedger(
            [*request.detection_result.evidence, *request.existing_evidence]
        )
        score = config.initial_score
        findings: list[Finding] = []
        invoked: list[AgentInvocation] = []
        agent_results: list[SpecialistAgentResult] = []
        errors: list[str] = []
        usage_by_agent: dict[str, dict[str, int]] = {}
        tool_calls = 0
        steps = 0
        input_tokens = 0
        output_tokens = 0
        direct_evidence = False
        low_delta_rounds = 0
        stop_reason: Optional[StopReason] = None
        seen_findings: set[tuple[str, tuple[str, ...]]] = set()

        for trigger in request.detection_result.triggers:
            missing = [ref for ref in trigger.evidence_refs if not ledger.contains(ref)]
            if missing:
                errors.append(
                    f"trigger:{trigger.type}:missing_evidence_refs={','.join(missing)}"
                )

        try:
            gateway_tools = await self._gateway.list_tools(request_id, traceparent)
        except Exception as exc:
            gateway_tools = []
            errors.append(f"tools:list:{type(exc).__name__}")

        trigger_text = " ".join(
            f"{trigger.type}: {trigger.reason}"
            for trigger in request.detection_result.triggers
        )
        ranked_agents = self._rank_agents(
            request.detection_result.subject,
            ledger.items(),
            trigger_text,
            config.agent_priorities,
        )

        for agent in ranked_agents:
            if len(invoked) >= config.max_agent_calls or steps >= config.max_steps:
                stop_reason = "budget_exhausted"
                break
            if input_tokens + output_tokens >= config.max_total_tokens:
                stop_reason = "budget_exhausted"
                break
            routing_score = agent.routing_score(
                request.detection_result.subject, ledger.items(), trigger_text
            )
            if routing_score == 0:
                continue
            reason = (
                f"case_type={agent.name}, "
                f"priority={config.agent_priorities.get(agent.name, 100)}, "
                f"routing_score={routing_score}"
            )
            invoked.append(
                AgentInvocation(
                    agent=agent.name,
                    case_type=agent.name,
                    sequence=len(invoked) + 1,
                    routing_score=routing_score,
                    reason=reason,
                )
            )
            usage_by_agent[agent.name] = {
                "calls": 1,
                "tool_calls": 0,
                "tokens": 0,
            }
            remaining_tokens = config.max_total_tokens - input_tokens - output_tokens
            if remaining_tokens < 64:
                stop_reason = "budget_exhausted"
                break
            remaining_tool_calls = min(
                config.max_tool_calls - tool_calls,
                max(config.max_steps - steps - 1, 0),
            )

            async def execute_tool(name: str, arguments: dict[str, Any]):
                return await self._gateway.call_tool(
                    name, arguments, request_id, traceparent
                )

            try:
                run = await agent.run(
                    request.detection_result.subject,
                    ledger.items(),
                    trigger_text,
                    min(config.max_output_tokens_per_agent, remaining_tokens),
                    gateway_tools,
                    execute_tool,
                    remaining_tool_calls,
                )
            except Exception as exc:
                errors.append(f"agent:{agent.name}:{str(exc)}")
                steps += 1
                continue

            input_tokens += run.input_tokens
            output_tokens += run.output_tokens
            usage_by_agent[agent.name]["tool_calls"] = len(run.tool_calls)
            usage_by_agent[agent.name]["tokens"] = run.input_tokens + run.output_tokens
            for call in run.tool_calls:
                tool_calls += 1
                steps += 1
                if call.succeeded and call.payload is not None:
                    ledger.add_tool_result(
                        (
                            f"{request.case_id}:tool:{tool_calls}:"
                            f"{agent.name}:{call.name}"
                        ),
                        call.name,
                        call.payload,
                    )
                else:
                    errors.append(f"tool:{agent.name}:{call.name}:{call.error}")
            processed = self._score_aggregator.aggregate(
                agent.name,
                run.analysis,
                agent.item_score_weights,
                (item.id for item in ledger.items()),
            )
            agent_results.append(processed)
            if processed.rejected_item_scores:
                errors.append(
                    f"agent:{agent.name}:rejected_item_scores="
                    f"{processed.rejected_item_scores}"
                )
            validated, rejected = ledger.validate_findings(run.analysis.findings)
            if rejected:
                errors.append(f"agent:{agent.name}:rejected_uncited_findings={rejected}")
            unique = []
            for finding in validated:
                fingerprint = (finding.type, tuple(sorted(finding.evidence_refs)))
                if fingerprint not in seen_findings:
                    unique.append(finding)
                    seen_findings.add(fingerprint)
            previous_score = score
            combined_score = combine_agent_scores(agent_results)
            if combined_score is not None:
                score = combined_score
            delta = score - previous_score
            findings.extend(unique)
            steps += 1
            direct_confidences = [
                finding.confidence
                for finding in unique
                if finding.impact == "supports_fraud"
                and config.stopping_rule_enabled("direct_evidence")
                and finding.confidence >= config.direct_evidence_confidence
            ]
            direct_evidence = direct_evidence or (
                run.analysis.direct_evidence_found and bool(direct_confidences)
            )
            if direct_evidence:
                score = max(
                    score,
                    config.fraud_threshold,
                    max(direct_confidences, default=config.direct_evidence_confidence),
                )
                delta = score - previous_score
            low_delta_rounds = (
                low_delta_rounds + 1
                if abs(delta) < config.minimum_score_delta
                else 0
            )

            if direct_evidence:
                stop_reason = "direct_evidence"
                break
            if score >= config.fraud_threshold:
                stop_reason = "fraud_threshold"
                break
            if score <= config.normal_threshold:
                stop_reason = "false_positive_evidence"
                break
            if (
                config.stopping_rule_enabled("diminishing_returns")
                and low_delta_rounds >= config.diminishing_return_rounds
            ):
                stop_reason = "diminishing_returns"
                break

        has_assessment = bool(
            findings
            or any(result.score_aggregate is not None for result in agent_results)
        )
        if stop_reason is None:
            if not has_assessment:
                stop_reason = "insufficient_evidence"
            elif len(invoked) >= config.max_agent_calls or steps >= config.max_steps:
                stop_reason = "budget_exhausted"
            else:
                stop_reason = "insufficient_evidence"

        verdict = verdict_for(score, config, has_assessment)
        summaries = [
            f"{finding.type}: {finding.description}" for finding in findings[:3]
        ]
        summary = (
            "; ".join(summaries)
            if summaries
            else (
                "; ".join(result.raw_analysis.summary for result in agent_results[:3])
                if agent_results
                else "Investigation completed without sufficiently supported findings."
            )
        )
        scoreboard = ScoreboardState(
            status="stopped",
            config_ref=request.scoreboard_config_ref,
            scoring_policy_version=config.scoring_policy_version,
            fraud_score=score,
            usage=ScoreboardUsage(
                agent_calls=len(invoked),
                tool_calls=tool_calls,
                investigation_steps=steps,
                tokens=input_tokens + output_tokens,
                cost_usd=0.0,
            ),
            budget=config.budget,
            agent_usage=[
                AgentUsage(
                    agent_id=agent_id,
                    calls=usage["calls"],
                    tool_calls=usage["tool_calls"],
                    tokens=usage["tokens"],
                    cost_usd=0.0,
                )
                for agent_id, usage in usage_by_agent.items()
            ],
            stop_reason=stop_reason,
            updated_at=datetime.now(timezone.utc),
        )
        return InvestigationResult(
            case_id=request.case_id,
            subject=request.detection_result.subject,
            verdict=verdict,
            confidence=confidence_for(score, has_assessment),
            summary=summary,
            findings=findings,
            evidence=ledger.items(),
            agents_invoked=invoked,
            agent_results=agent_results,
            scoreboard=scoreboard.model_dump(mode="json", exclude_none=True),
            stop_reason=stop_reason,
        )

    def _rank_agents(
        self,
        subject: Subject,
        evidence: list[Evidence],
        trigger_text: str,
        priorities: dict[str, int],
    ) -> list[DomainAgent]:
        """Let the orchestrator choose which investigation case type runs first."""
        return sorted(
            (agent for agent in self._agents if agent.name in priorities),
            key=lambda agent: (
                -agent.routing_score(subject, evidence, trigger_text),
                priorities.get(agent.name, 100),
                agent.name,
            ),
        )
