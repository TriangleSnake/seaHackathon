"""Budgeted, evidence-first dynamic multi-agent orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.base import DomainAgent
from app.agents.orchestrator import OrchestratorAgent
from app.domain.models import (
    AgentInvocation,
    AgentUsage,
    Evidence,
    Finding,
    InvestigationRequest,
    InvestigationResult,
    OrchestratorDecision,
    OrchestratorReport,
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
        orchestrator_agent: Optional[OrchestratorAgent] = None,
    ) -> None:
        self._gateway = gateway
        self._policies = policy_repository
        self._agents = agents
        self._score_aggregator = score_aggregator or AgentScoreAggregator()
        self._orchestrator_agent = orchestrator_agent

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(agent.name for agent in self._agents)

    @property
    def orchestrator_name(self) -> Optional[str]:
        return (
            self._orchestrator_agent.name
            if self._orchestrator_agent is not None
            else None
        )

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
        decisions: list[OrchestratorDecision] = []
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
        decision_fingerprints: set[tuple[str, str, tuple[str, ...]]] = set()
        usage_by_agent["orchestrator"] = {
            "calls": 0,
            "tool_calls": 0,
            "tokens": 0,
        }

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
        enabled_agents = {
            agent.name: agent
            for agent in self._agents
            if agent.name in config.agent_priorities
        }
        invocation_counts = {name: 0 for name in enabled_agents}

        while True:
            if len(invoked) >= config.max_agent_calls or steps >= config.max_steps:
                stop_reason = "budget_exhausted"
                break
            decision_context = self._orchestrator_context(
                request,
                enabled_agents,
                invocation_counts,
                invoked,
                agent_results,
                findings,
                ledger,
                score,
                config.max_agent_calls - len(invoked),
                config.max_tool_calls - tool_calls,
                config.max_steps - steps,
            )
            decision: Optional[OrchestratorDecision] = None
            if self._orchestrator_agent is not None:
                try:
                    decision, decision_input, decision_output = (
                        await self._orchestrator_agent.decide(
                            decision_context,
                            500,
                        )
                    )
                    steps += 1
                    input_tokens += decision_input
                    output_tokens += decision_output
                    usage_by_agent["orchestrator"]["calls"] += 1
                    usage_by_agent["orchestrator"]["tokens"] += (
                        decision_input + decision_output
                    )
                except Exception as exc:
                    errors.append(f"orchestrator:decision:{type(exc).__name__}")

            if decision is None:
                decision = self._fallback_decision(
                    request.detection_result.subject,
                    ledger.items(),
                    trigger_text,
                    config.agent_priorities,
                    enabled_agents,
                    invocation_counts,
                    bool(agent_results),
                )

            if decision.action == "stop":
                if not agent_results and enabled_agents:
                    decision = self._fallback_decision(
                        request.detection_result.subject,
                        ledger.items(),
                        trigger_text,
                        config.agent_priorities,
                        enabled_agents,
                        invocation_counts,
                        False,
                    )
                else:
                    decisions.append(decision)
                    break

            if decision.agent is None or decision.agent not in enabled_agents:
                errors.append("orchestrator:decision:invalid_agent")
                decision = self._fallback_decision(
                    request.detection_result.subject,
                    ledger.items(),
                    trigger_text,
                    config.agent_priorities,
                    enabled_agents,
                    invocation_counts,
                    bool(agent_results),
                )
                if decision.action == "stop" or decision.agent is None:
                    break

            selected_name = decision.agent
            assert selected_name is not None
            action = decision.action
            if action == "continue_agent" and invocation_counts[selected_name] == 0:
                action = "invoke_agent"
            elif action == "invoke_agent" and invocation_counts[selected_name] > 0:
                action = "continue_agent"
            fingerprint = (
                action,
                selected_name,
                tuple(sorted(decision.investigation_focus)),
            )
            if fingerprint in decision_fingerprints:
                errors.append("orchestrator:decision:duplicate")
                fallback = self._fallback_decision(
                    request.detection_result.subject,
                    ledger.items(),
                    trigger_text,
                    config.agent_priorities,
                    enabled_agents,
                    invocation_counts,
                    True,
                )
                if fallback.action == "stop" or fallback.agent is None:
                    stop_reason = "diminishing_returns"
                    break
                decision = fallback
                selected_name = fallback.agent
                action = fallback.action
                fingerprint = (
                    action,
                    selected_name,
                    tuple(sorted(fallback.investigation_focus)),
                )
            decision_fingerprints.add(fingerprint)
            decision = OrchestratorDecision(
                action=action,
                agent=selected_name,
                reason=decision.reason,
                investigation_focus=decision.investigation_focus,
            )
            decisions.append(decision)
            agent = enabled_agents[selected_name]
            routing_score = agent.routing_score(
                request.detection_result.subject, ledger.items(), trigger_text
            )
            invoked.append(
                AgentInvocation(
                    agent=agent.name,
                    case_type=agent.name,
                    sequence=len(invoked) + 1,
                    routing_score=routing_score,
                    reason=self._decision_reason(decision, action),
                )
            )
            invocation_counts[agent.name] += 1
            usage_by_agent.setdefault(
                agent.name, {"calls": 0, "tool_calls": 0, "tokens": 0}
            )
            usage_by_agent[agent.name]["calls"] += 1
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
                    self._specialist_focus(trigger_text, decision),
                    config.max_output_tokens_per_agent,
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
            usage_by_agent[agent.name]["tool_calls"] += len(run.tool_calls)
            usage_by_agent[agent.name]["tokens"] += run.input_tokens + run.output_tokens
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
                and any(
                    contribution.score == 5
                    and contribution.is_direct_evidence
                    and bool(
                        set(contribution.evidence_refs)
                        & set(finding.evidence_refs)
                    )
                    for contribution in (
                        processed.score_aggregate.contributions
                        if processed.score_aggregate is not None
                        else []
                    )
                )
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

            # The LLM orchestrator receives these signals on the next round and
            # decides whether another specialist can materially improve the case.
            # Python only forces hard resource limits.

        has_assessment = bool(
            findings
            or any(result.score_aggregate is not None for result in agent_results)
        )
        if stop_reason is None:
            if direct_evidence:
                stop_reason = "direct_evidence"
            elif score + 1e-9 >= config.fraud_threshold:
                stop_reason = "fraud_threshold"
            elif score - 1e-9 <= config.normal_threshold:
                stop_reason = "false_positive_evidence"
            elif (
                config.stopping_rule_enabled("diminishing_returns")
                and low_delta_rounds >= config.diminishing_return_rounds
            ):
                stop_reason = "diminishing_returns"
            elif not has_assessment:
                stop_reason = "insufficient_evidence"
            else:
                stop_reason = "insufficient_evidence"

        verdict = verdict_for(score, config, has_assessment)
        confidence = confidence_for(score, has_assessment)
        report = await self._final_report(
            request,
            invoked,
            decisions,
            agent_results,
            findings,
            ledger,
            verdict,
            score,
            confidence,
            stop_reason,
            errors,
        )
        if report[1] or report[2]:
            input_tokens += report[1]
            output_tokens += report[2]
            usage_by_agent["orchestrator"]["calls"] += 1
            usage_by_agent["orchestrator"]["tokens"] += report[1] + report[2]
        orchestrator_report = report[0]
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
            confidence=confidence,
            summary=orchestrator_report.summary,
            findings=findings,
            evidence=ledger.items(),
            agents_invoked=invoked,
            agent_results=agent_results,
            scoreboard=scoreboard.model_dump(mode="json", exclude_none=True),
            stop_reason=stop_reason,
        )

    @staticmethod
    def _specialist_focus(trigger_text: str, decision: OrchestratorDecision) -> str:
        focus = "；".join(decision.investigation_focus)
        return f"{trigger_text}\nOrchestrator investigation focus: {focus}" if focus else trigger_text

    @staticmethod
    def _decision_reason(decision: OrchestratorDecision, action: str) -> str:
        focus = "；".join(decision.investigation_focus)
        prefix = "繼續調查" if action == "continue_agent" else "啟動調查"
        return (
            f"{prefix}：{decision.reason} 調查焦點：{focus}"
            if focus
            else f"{prefix}：{decision.reason}"
        )

    @staticmethod
    def _public_results(results: list[SpecialistAgentResult]) -> list[dict[str, Any]]:
        public = []
        for result in results:
            aggregate = result.score_aggregate
            public.append(
                {
                    "agent": result.agent,
                    "raw_analysis": result.raw_analysis.model_dump(mode="json"),
                    "score_aggregate": (
                        {
                            "weighted_score": aggregate.weighted_score,
                            "confidence": aggregate.confidence,
                            "coverage": aggregate.coverage,
                        }
                        if aggregate is not None
                        else None
                    ),
                    "rejected_item_scores": result.rejected_item_scores,
                }
            )
        return public

    def _orchestrator_context(
        self,
        request: InvestigationRequest,
        enabled_agents: dict[str, DomainAgent],
        invocation_counts: dict[str, int],
        invoked: list[AgentInvocation],
        agent_results: list[SpecialistAgentResult],
        findings: list[Finding],
        ledger: EvidenceLedger,
        score: float,
        remaining_agent_calls: int,
        remaining_tool_calls: int,
        remaining_steps: int,
    ) -> dict[str, Any]:
        responsibilities = {
            "order": "訂單、交易、付款、配送、退款與爭議",
            "chat": "訊息、對話、URL、附件、釣魚與參與帳號",
            "marketplace_info": "商店、商品、價格、圖片、評論、檢舉與賣家",
        }
        return {
            "case": request.model_dump(mode="json"),
            "available_specialists": [
                {
                    "agent": name,
                    "responsibility": responsibilities[name],
                    "times_invoked": invocation_counts[name],
                }
                for name in enabled_agents
            ],
            "invocation_history": [item.model_dump(mode="json") for item in invoked],
            "specialist_results": self._public_results(agent_results),
            "validated_findings": [item.model_dump(mode="json") for item in findings],
            "current_fraud_score": round(score, 6),
            "allowed_evidence_refs": [item.id for item in ledger.items()],
            "remaining_budget": {
                "agent_calls": max(remaining_agent_calls, 0),
                "tool_calls": max(remaining_tool_calls, 0),
                "steps": max(remaining_steps, 0),
            },
        }

    def _fallback_decision(
        self,
        subject: Subject,
        evidence: list[Evidence],
        trigger_text: str,
        priorities: dict[str, int],
        enabled_agents: dict[str, DomainAgent],
        invocation_counts: dict[str, int],
        has_results: bool,
    ) -> OrchestratorDecision:
        if has_results:
            return OrchestratorDecision(
                action="stop",
                reason="Orchestrator 無法產生下一步，保留目前已驗證結果並停止。",
            )
        ranked = self._rank_agents(subject, evidence, trigger_text, priorities)
        available = [item for item in ranked if item.name in enabled_agents]
        if not available:
            return OrchestratorDecision(
                action="stop", reason="沒有可用的 Sub-agent 可執行調查。"
            )
        selected = min(available, key=lambda item: invocation_counts[item.name])
        return OrchestratorDecision(
            action="invoke_agent",
            agent=selected.name,
            reason="LLM Orchestrator 無法使用，依案件類型啟用備援路由。",
            investigation_focus=["檢查案件主要風險與相關證據"],
        )

    async def _final_report(
        self,
        request: InvestigationRequest,
        invoked: list[AgentInvocation],
        decisions: list[OrchestratorDecision],
        agent_results: list[SpecialistAgentResult],
        findings: list[Finding],
        ledger: EvidenceLedger,
        verdict: str,
        score: float,
        confidence: float,
        stop_reason: StopReason,
        errors: list[str],
    ) -> tuple[OrchestratorReport, int, int]:
        if self._orchestrator_agent is not None:
            try:
                report, input_used, output_used = await self._orchestrator_agent.report(
                    {
                        "case_id": request.case_id,
                        "subject": request.detection_result.subject.model_dump(),
                        "deterministic_verdict": verdict,
                        "fraud_score": round(score, 6),
                        "verdict_confidence": round(confidence, 6),
                        "stop_reason": stop_reason,
                        "invocation_history": [
                            item.model_dump(mode="json") for item in invoked
                        ],
                        "decision_history": [
                            item.model_dump(mode="json") for item in decisions
                        ],
                        "specialist_results": self._public_results(agent_results),
                        "validated_findings": [
                            item.model_dump(mode="json") for item in findings
                        ],
                        "allowed_evidence_refs": sorted(
                            item.id for item in ledger.items()
                        ),
                    },
                    1600,
                )
                return report, input_used, output_used
            except Exception as exc:
                errors.append(f"orchestrator:report:{type(exc).__name__}")
        summaries = [item.raw_analysis.summary for item in agent_results]
        summary = (
            "；".join(summaries)
            if summaries
            else "調查已完成，但沒有足夠證據形成受支持的發現。"
        )
        return (
            OrchestratorReport(
                summary=summary,
            ),
            0,
            0,
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
