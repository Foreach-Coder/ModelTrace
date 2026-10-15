"""Typed failure details shared by structured model completion adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionFailureDetails:
    """Partial data received before a model completion failed."""

    text: str | None = None
    usage: dict[str, object] | None = None


class StructuredCompletionError(RuntimeError):
    """A failed completion that may still carry transport-provided data."""

    def __init__(
        self,
        message: str,
        *,
        details: CompletionFailureDetails | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or CompletionFailureDetails()
