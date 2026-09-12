from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from .contracts import ContractValidationError, ContractValidator
from .models import (
    AssociationRequest,
    AssociationResult,
    InvestigationRequest,
    PatrolRequest,
    PatrolResult,
)
from .settings import Settings


class ServiceClientError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class _JsonServiceClient:
    def __init__(self, service: str, base_url: str, client: httpx.AsyncClient) -> None:
        self._service = service
        self._base_url = base_url
        self._client = client

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        request_id: str,
        traceparent: str | None = None,
        idempotency_key: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        headers = {"X-Request-ID": request_id}
        if traceparent:
            headers["traceparent"] = traceparent
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = await self._client.post(
                f"{self._base_url}{path}", json=payload, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ServiceClientError("timeout", f"{self._service} request timed out") from exc
        except httpx.TransportError as exc:
            raise ServiceClientError(
                "connection_error", f"{self._service} transport failed"
            ) from exc
        if not 200 <= response.status_code < 300:
            raise ServiceClientError(
                "http_status", f"{self._service} returned HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceClientError(
                "malformed_json", f"{self._service} returned malformed JSON"
            ) from exc


def _contract_error(service: str, exc: Exception) -> ServiceClientError:
    return ServiceClientError("contract_invalid", f"{service} contract validation failed: {exc}")


class PatrolClient(_JsonServiceClient):
    def __init__(self, base_url: str, client: httpx.AsyncClient, contracts: ContractValidator) -> None:
        super().__init__("Patrol", base_url, client)
        self._contracts = contracts

    async def run(
        self, request: PatrolRequest, request_id: str, traceparent: str | None = None
    ) -> PatrolResult:
        payload = request.model_dump(mode="json", exclude_none=True)
        try:
            self._contracts.patrol_request(payload)
        except ContractValidationError as exc:
            raise _contract_error("Patrol request", exc) from exc
        raw = await self._post(
            "/patrol/run",
            payload,
            request_id,
            traceparent,
            request.run_id,
            {"X-Upstream-Orchestration": "association-first"},
        )
        try:
            self._contracts.patrol_result(raw)
            result = PatrolResult.model_validate(raw)
        except (ContractValidationError, ValidationError) as exc:
            raise _contract_error("Patrol response", exc) from exc
        if result.run_id != request.run_id:
            raise ServiceClientError("lineage_mismatch", "Patrol result run_id mismatch")
        if result.strategy != request.strategy:
            raise ServiceClientError("lineage_mismatch", "Patrol result strategy mismatch")
        subjects = [(item.subject.type, item.subject.id) for item in result.discoveries]
        if len(subjects) != len(set(subjects)):
            raise ServiceClientError(
                "lineage_mismatch", "Patrol result contains duplicate discovery subjects"
            )
        return result


class AssociationClient(_JsonServiceClient):
    def __init__(self, base_url: str, client: httpx.AsyncClient, contracts: ContractValidator) -> None:
        super().__init__("Association", base_url, client)
        self._contracts = contracts

    async def associate(
        self, request: AssociationRequest, traceparent: str | None = None
    ) -> AssociationResult:
        payload = request.model_dump(mode="json", exclude_none=True)
        try:
            self._contracts.association_request(payload)
        except ContractValidationError as exc:
            raise _contract_error("Association request", exc) from exc
        raw = await self._post(
            "/associate", payload, request.case_id, traceparent, request.case_id
        )
        try:
            self._contracts.association_result(raw)
            result = AssociationResult.model_validate(raw)
        except (ContractValidationError, ValidationError) as exc:
            raise _contract_error("Association response", exc) from exc
        if result.case_id != request.case_id:
            raise ServiceClientError("lineage_mismatch", "Association result case_id mismatch")
        if result.strategy != request.strategy:
            raise ServiceClientError("lineage_mismatch", "Association result strategy mismatch")
        root_nodes = [node for node in result.nodes if node.id == request.subject.id]
        if root_nodes and any(node.type != request.subject.type for node in root_nodes):
            raise ServiceClientError("lineage_mismatch", "Association root subject mismatch")
        if (result.edges or result.related_subjects) and not any(
            node.type == request.subject.type and node.id == request.subject.id
            for node in result.nodes
        ):
            raise ServiceClientError(
                "lineage_mismatch", "Association graph omits the requested root subject"
            )
        if any(related.subject == request.subject for related in result.related_subjects):
            raise ServiceClientError(
                "lineage_mismatch", "Association related subjects repeat the root subject"
            )
        return result


class InvestigationClient(_JsonServiceClient):
    def __init__(self, base_url: str, client: httpx.AsyncClient, contracts: ContractValidator) -> None:
        super().__init__("Investigation", base_url, client)
        self._contracts = contracts

    async def investigate(
        self, request: InvestigationRequest, traceparent: str | None = None
    ) -> dict[str, Any]:
        payload = request.model_dump(mode="json", exclude_none=True)
        try:
            self._contracts.investigation_request(payload)
        except ContractValidationError as exc:
            raise _contract_error("Investigation request", exc) from exc
        raw = await self._post(
            "/investigate", payload, request.case_id, traceparent, request.case_id
        )
        try:
            self._contracts.investigation_result(raw)
        except ContractValidationError as exc:
            raise _contract_error("Investigation response", exc) from exc
        if raw["case_id"] != request.case_id:
            raise ServiceClientError("lineage_mismatch", "Investigation result case_id mismatch")
        expected_subject = request.detection_result.subject.model_dump(mode="json")
        if raw["subject"] != expected_subject:
            raise ServiceClientError("lineage_mismatch", "Investigation result subject mismatch")
        return raw


class PipelineClients:
    def __init__(
        self,
        patrol: PatrolClient,
        association: AssociationClient,
        investigation: InvestigationClient,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.patrol = patrol
        self.association = association
        self.investigation = investigation
        self._http_client = http_client

    @classmethod
    def build(
        cls, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> "PipelineClients":
        contracts = ContractValidator(settings.schema_dir)
        http_client = httpx.AsyncClient(
            timeout=settings.timeout_seconds, transport=transport
        )
        return cls(
            PatrolClient(settings.patrol_url, http_client, contracts),
            AssociationClient(settings.association_url, http_client, contracts),
            InvestigationClient(settings.investigation_url, http_client, contracts),
            http_client,
        )

    async def close(self) -> None:
        await self._http_client.aclose()
