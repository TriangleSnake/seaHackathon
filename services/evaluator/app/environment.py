from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


class IsolatedEnvironmentError(RuntimeError):
    pass


class PostgresEnvironmentControl:
    """Minimal adapter around the existing Environment simulation control plane."""

    def __init__(self, database_url: str) -> None:
        parsed = urlparse(database_url)
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port != 55432
            or parsed.username != "fraud"
            or parsed.path != "/fraud_intelligence"
        ):
            raise IsolatedEnvironmentError(
                "Member 4 live evaluation requires the isolated "
                "127.0.0.1:55432/fraud_intelligence database"
            )
        self._database_url = database_url

    def verify_isolated(self, expected_scenario: str) -> Mapping[str, Any]:
        row = self._fetch_state(include_identity=True)
        if (
            row["database"] != "fraud_intelligence"
            or row["user"] != "fraud"
            or row["scenario_name"] != expected_scenario
        ):
            raise IsolatedEnvironmentError(
                "Connected database does not match the isolated validation identity"
            )
        return self._overview(row)

    def set_simulation_time_once(self, value: datetime) -> Mapping[str, Any]:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Simulation time must include a timezone offset")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_simulation_time(%s)", (value,))
            connection.commit()
        return self.get_environment_overview()

    def get_environment_overview(self) -> Mapping[str, Any]:
        return self._overview(self._fetch_state(include_identity=False))

    def _fetch_state(self, *, include_identity: bool) -> dict[str, Any]:
        identity = "current_database(), current_user, " if include_identity else ""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT "
                    + identity
                    + "scenario_name, simulation_time, initial_time, updated_at "
                    "FROM simulation_state WHERE singleton_id = 1"
                )
                values = cursor.fetchone()
        if values is None:
            raise IsolatedEnvironmentError("Environment simulation_state is missing")
        if include_identity:
            database, user, scenario, simulation, initial, updated = values
            return {
                "database": database,
                "user": user,
                "scenario_name": scenario,
                "simulation_time": simulation,
                "initial_time": initial,
                "updated_at": updated,
            }
        scenario, simulation, initial, updated = values
        return {
            "scenario_name": scenario,
            "simulation_time": simulation,
            "initial_time": initial,
            "updated_at": updated,
        }

    @staticmethod
    def _overview(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "simulation": {
                "scenario_name": row["scenario_name"],
                "simulation_time": row["simulation_time"].isoformat(),
                "initial_time": row["initial_time"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }
        }

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise IsolatedEnvironmentError(
                "psycopg is required for the isolated Environment adapter"
            ) from exc
        return psycopg.connect(self._database_url)
