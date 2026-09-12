"""Evaluator-specific failures with stable, user-facing messages."""


class EvaluationError(Exception):
    """Base class for expected evaluation failures."""


class ContractError(EvaluationError):
    """The shared evaluation request is malformed."""


class UnsupportedPolicyError(EvaluationError):
    """No concrete evaluator is available for a policy type."""


class EvaluationPlanError(EvaluationError):
    """The trusted evaluation plan is missing or inconsistent."""


class DatasetAccessError(EvaluationError):
    """A dataset cannot be loaded in the requested context."""


class HoldoutAccessError(DatasetAccessError):
    """Builder/development access attempted to read holdout data."""


class SnapshotGuardError(EvaluationError):
    """Environment snapshot metadata is unavailable, malformed, or changed."""


class BaselineExecutionError(EvaluationError):
    """The baseline could not run, so comparison is impossible."""
