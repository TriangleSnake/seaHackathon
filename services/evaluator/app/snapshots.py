from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .errors import SnapshotGuardError
from .models import DatasetSnapshot


class EnvironmentOverviewSource(Protocol):
    """Synchronous boundary for the Environment's read-only overview tool."""

    def get_environment_overview(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SnapshotIdentity:
    scenario_name: str
    simulation_time: datetime
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_name, str) or not self.scenario_name.strip():
            raise SnapshotGuardError(
                "Environment snapshot scenario_name must be a non-empty string"
            )
        _require_aware(self.simulation_time, "simulation_time")
        if self.updated_at is not None:
            _require_aware(self.updated_at, "updated_at")


class EnvironmentSnapshotGuard:
    """Fail-closed pre/post guard around one evaluator execution.

    This deliberately does not provide locking. It records the Environment's
    operational snapshot immediately before policy execution and verifies that
    the identity is unchanged immediately afterward.
    """

    def __init__(self, source: EnvironmentOverviewSource) -> None:
        self._source = source

    def capture(self, expected: DatasetSnapshot) -> SnapshotIdentity:
        observed = self.read_identity()
        if (
            observed.scenario_name != expected.scenario_name
            or observed.simulation_time != expected.simulation_time
        ):
            raise SnapshotGuardError(
                "Environment snapshot does not match the evaluation dataset: "
                f"expected scenario={expected.scenario_name!r}, "
                f"simulation_time={expected.simulation_time.isoformat()}; "
                f"observed scenario={observed.scenario_name!r}, "
                f"simulation_time={observed.simulation_time.isoformat()}"
            )
        return observed

    def verify_unchanged(self, before: SnapshotIdentity) -> None:
        after = self.read_identity()
        if after != before:
            raise SnapshotGuardError(
                "Environment snapshot changed during evaluation: "
                f"before={_describe(before)}; after={_describe(after)}"
            )

    def read_identity(self) -> SnapshotIdentity:
        try:
            overview = self._source.get_environment_overview()
        except SnapshotGuardError:
            raise
        except Exception as exc:
            raise SnapshotGuardError(
                f"Environment overview could not be read: {type(exc).__name__}: {exc}"
            ) from exc

        if not isinstance(overview, Mapping):
            raise SnapshotGuardError("Environment overview must be an object")
        simulation = overview.get("simulation")
        if not isinstance(simulation, Mapping):
            raise SnapshotGuardError(
                "Environment overview must contain a simulation object"
            )

        scenario_name = simulation.get("scenario_name")
        if not isinstance(scenario_name, str) or not scenario_name.strip():
            raise SnapshotGuardError(
                "Environment overview scenario_name must be a non-empty string"
            )

        simulation_time = _parse_aware_datetime(
            simulation.get("simulation_time"), "simulation_time"
        )
        updated_value = simulation.get("updated_at")
        updated_at = (
            None
            if updated_value is None
            else _parse_aware_datetime(updated_value, "updated_at")
        )
        return SnapshotIdentity(
            scenario_name=scenario_name,
            simulation_time=simulation_time,
            updated_at=updated_at,
        )


def _parse_aware_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SnapshotGuardError(
                f"Environment overview {field_name} must be an ISO-8601 datetime"
            ) from exc
    else:
        raise SnapshotGuardError(
            f"Environment overview {field_name} must be an ISO-8601 datetime"
        )
    _require_aware(parsed, field_name)
    return parsed


def _require_aware(value: datetime, field_name: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SnapshotGuardError(
            f"Environment snapshot {field_name} must include a timezone offset"
        )


def _describe(identity: SnapshotIdentity) -> str:
    updated_at = identity.updated_at.isoformat() if identity.updated_at else None
    return (
        f"scenario={identity.scenario_name!r}, "
        f"simulation_time={identity.simulation_time.isoformat()}, "
        f"updated_at={updated_at}"
    )
