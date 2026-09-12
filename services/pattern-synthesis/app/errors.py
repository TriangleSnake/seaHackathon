"""Explicit fail-closed errors for the Pattern Synthesis boundary."""

from __future__ import annotations


class SynthesisError(RuntimeError):
    def __init__(self, code: str, message: str, issues: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.issues = issues


class SynthesisUnavailableError(SynthesisError):
    def __init__(self, message: str) -> None:
        super().__init__("synthesizer_unavailable", message)
