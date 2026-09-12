from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .adapters import (
    AdapterError,
    build_association_request,
    build_investigation_request,
    deterministic_case_id,
    deterministic_pipeline_run_id,
)
from .clients import PipelineClients, ServiceClientError
from .contracts import ContractValidationError, ContractValidator
from .models import (
    AssociationStage,
    DiscoveryPipelineItem,
    InvestigationStage,
    PatrolRequest,
    PatrolStage,
    PipelineError,
    UpstreamPipelineResult,
)
from .settings import Settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _pipeline_error(exc: Exception) -> PipelineError:
    if isinstance(exc, ServiceClientError):
        return PipelineError(kind=exc.kind, message=str(exc))
    if isinstance(exc, (AdapterError, ContractValidationError)):
        return PipelineError(kind="contract_invalid", message=str(exc))
    return PipelineError(kind="internal_error", message=f"{type(exc).__name__}: {exc}")


class DiscoveryPipelineOrchestrator:
    """Sequential, audit-first orchestration across the three stable HTTP APIs."""

    def __init__(
        self,
        clients: PipelineClients,
        settings: Settings,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._clients = clients
        self._settings = settings
        self._clock = clock
        self._contracts = ContractValidator(settings.schema_dir)

    async def run(
        self,
        request: PatrolRequest,
        request_id: str | None = None,
        traceparent: str | None = None,
    ) -> UpstreamPipelineResult:
        pipeline_started = self._clock()
        pipeline_run_id = deterministic_pipeline_run_id(request.run_id)
        patrol_started = self._clock()
        try:
            patrol_result = await self._clients.patrol.run(
                request, request_id or pipeline_run_id, traceparent
            )
        except Exception as exc:
            completed = self._clock()
            return UpstreamPipelineResult(
                pipeline_run_id=pipeline_run_id,
                patrol_run_id=request.run_id,
                status="failed",
                started_at=pipeline_started,
                completed_at=completed,
                patrol=PatrolStage(
                    status="failed",
                    request=request,
                    started_at=patrol_started,
                    completed_at=completed,
                    error=_pipeline_error(exc),
                ),
                discoveries=[],
            )

        patrol_completed = self._clock()
        patrol_stage = PatrolStage(
            status="succeeded",
            request=request,
            result=patrol_result,
            started_at=patrol_started,
            completed_at=patrol_completed,
        )
        discoveries: list[DiscoveryPipelineItem] = []
        for discovery in patrol_result.discoveries:
            case_id = deterministic_case_id(patrol_result, discovery)
            association_started = self._clock()
            association_request = None
            try:
                association_request = build_association_request(patrol_result, discovery)
                self._contracts.association_request(
                    association_request.model_dump(mode="json", exclude_none=True)
                )
                association_result = await self._clients.association.associate(
                    association_request, traceparent
                )
            except Exception as exc:
                association_completed = self._clock()
                discoveries.append(
                    DiscoveryPipelineItem(
                        subject=discovery.subject,
                        case_id=case_id,
                        patrol_discovery=discovery,
                        association=AssociationStage(
                            status="failed",
                            request=association_request,
                            started_at=association_started,
                            completed_at=association_completed,
                            error=_pipeline_error(exc),
                        ),
                        investigation=InvestigationStage(
                            status="skipped",
                            error=PipelineError(
                                kind="upstream_failed",
                                message="Investigation skipped because Association failed",
                            ),
                        ),
                    )
                )
                continue

            association_completed = self._clock()
            association_stage = AssociationStage(
                status="succeeded",
                request=association_request,
                result=association_result,
                started_at=association_started,
                completed_at=association_completed,
            )
            investigation_started = self._clock()
            investigation_request = None
            try:
                investigation_request = build_investigation_request(
                    patrol_result,
                    discovery,
                    association_result,
                    self._settings.scoreboard_config_version,
                )
                self._contracts.investigation_request(
                    investigation_request.model_dump(mode="json", exclude_none=True)
                )
                investigation_result = await self._clients.investigation.investigate(
                    investigation_request, traceparent
                )
                investigation_stage = InvestigationStage(
                    status="succeeded",
                    request=investigation_request,
                    result=investigation_result,
                    started_at=investigation_started,
                    completed_at=self._clock(),
                )
            except Exception as exc:
                investigation_stage = InvestigationStage(
                    status="failed",
                    request=investigation_request,
                    started_at=investigation_started,
                    completed_at=self._clock(),
                    error=_pipeline_error(exc),
                )

            discoveries.append(
                DiscoveryPipelineItem(
                    subject=discovery.subject,
                    case_id=case_id,
                    patrol_discovery=discovery,
                    association=association_stage,
                    investigation=investigation_stage,
                )
            )

        succeeded = sum(
            item.investigation.status == "succeeded" for item in discoveries
        )
        if not discoveries or succeeded == len(discoveries):
            status = "succeeded"
        elif succeeded:
            status = "partial_failure"
        else:
            status = "failed"
        return UpstreamPipelineResult(
            pipeline_run_id=pipeline_run_id,
            patrol_run_id=request.run_id,
            status=status,
            started_at=pipeline_started,
            completed_at=self._clock(),
            patrol=patrol_stage,
            discoveries=discoveries,
        )

    async def close(self) -> None:
        await self._clients.close()
