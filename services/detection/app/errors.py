class CheckUnavailableError(ValueError):
    """A requested check cannot execute in this deployment."""


class CheckInconclusiveError(ValueError):
    """A check ran without sufficient input or classifier output for a decision."""
