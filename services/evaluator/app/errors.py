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


class BaselineExecutionError(EvaluationError):
    """The baseline could not run, so comparison is impossible."""


class DetectionExecutionError(EvaluationError):
    """Detection could not produce a trustworthy evaluation decision."""


class DetectionTransportError(DetectionExecutionError):
    """The evaluator could not communicate with Detection."""


class DetectionTimeoutError(DetectionTransportError):
    """Detection did not respond within the configured timeout."""


class DetectionHttpError(DetectionExecutionError):
    """Detection returned a non-success HTTP response."""

    def __init__(
        self, message: str, *, status_code: int, error_code: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class DetectionPolicyNotFoundError(DetectionHttpError):
    """The explicitly requested Detection policy does not exist."""


class DetectionRequestRejectedError(DetectionHttpError):
    """Detection rejected the requested subject, check, or request shape."""


class DetectionResponseError(DetectionExecutionError):
    """Detection returned a response that cannot be trusted or interpreted."""


class DetectionPolicyTraceError(DetectionResponseError):
    """Detection did not prove that it executed the requested policy version."""
